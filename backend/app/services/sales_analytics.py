"""판매 분석 (#357). 새 저장 없이 SALE 출고 이력을 수량으로 집계한다. 읽기만 하고 commit 하지 않는다.

- 판매 수량 = net_sales_by (SALE − 그 SALE 을 가리키는 정정, 폐기·기타 출고·조정 제외). 발주 추천의 net_sales 와 같은 함수다.
- 일평균·소진 예상일은 발주 추천과 같은 최근 30일 기준이라 두 화면 숫자가 같다(선택한 기간 7/90일과 무관).
- 소진 예상일 = 가용재고(현재고 + 입고 예정) ÷ 일평균. "곧 소진"(cover_alert=SHORT)은 발주 추천 대상과 같은 판정이다(재주문점 규칙).
- 쿼리는 품목 수와 무관하게 7번: 품목·공급업체, 기간 품목별, 기간 날짜별, 30일 품목별, 현재고·첫 입출고, 입고 예정 2번.
"""

from datetime import date, timedelta  # 날짜와 기간 경계
from fractions import Fraction  # 일평균을 분수 그대로 (추천과 같은 값)

from sqlalchemy import select  # SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.models import InventoryMovement, Product, Supplier  # 입출고 이력, 품목, 공급업체(리드타임)
from app.services.recommend import (  # 추천과 같은 상수·계산
    MIN_HISTORY_DAYS,  # 데이터 부족 14일
    SALES_WINDOW_DAYS,  # 30일
    available_stock,  # 가용재고 = 현재고 + 입고 예정
    calculate_recommendation,  # 추천 판정 (곧 소진 = 추천 대상)
    stock_status,  # SHORTAGE / NORMAL / UNKNOWN
)
from app.services.recommendations import (  # 품목별 입고 예정, (현재고, 첫 입출고 날짜)
    in_transit,
    stock_and_first_day,
)
from app.services.stock import net_sales, net_sales_by  # 순판매 (추천과 같은 규칙)

SOURCE = "SALE_MOVEMENTS"  # 출처: 판매 가져오기와 직접 입력한 판매 출고(SALE) 이력
SOURCE_NOTE = "판매 출고(SALE) 이력의 수량입니다. 판매 가져오기와 직접 입력한 판매가 모두 포함되고, 정정 수량은 빼고, 폐기·기타 출고는 넣지 않습니다. 금액은 저장하지 않아 수량만 보여 줍니다."
ABC_A, ABC_B = 80, 95  # ABC 등급 누적 비율(%): A 80, B 15(→95), C 나머지 5


def abc_grades(quantities: list[int]) -> list[str | None]:
    """판매량 내림차순 목록 → 등급. 이 품목 앞까지의 누적이 80% 미만이면 A, 95% 미만이면 B, 그 밖은 C. 판매 0 은 None.

    예) 50·30·15·5 (합 100): 앞 누적 0→A, 50→A, 80→B, 95→C. 1등은 혼자 90%여도 A 다.
    """
    total, before, grades = sum(quantities), 0, []
    for qty in quantities:
        if qty <= 0:
            grades.append(None)
        else:
            grades.append("A" if before * 100 < ABC_A * total else "B" if before * 100 < ABC_B * total else "C")  # 정수 비교 (소수 오차 없음)
        before += qty
    return grades


def cover(today: date, first_day: date | None, sales_30d: int, available: int) -> tuple[str, float | None, float | None]:
    """(상태, 일평균, 소진 예상일). 추천의 제외 순서(INSUFFICIENT_DATA → NO_SALES_30D)와 같은 기준. 숫자를 억지로 만들지 않는다.

    예) 30일 판매 300, 가용재고 50 → 일평균 10, 소진 예상 5.0일. 30일 판매 7, 가용재고 3 → 일평균 0.233…, 12.9일.
    """
    if first_day is None or (today - first_day).days < MIN_HISTORY_DAYS:  # 이력 없음 또는 14일 미만
        return "INSUFFICIENT_DATA", None, None
    if sales_30d <= 0:  # 최근 30일 순판매 없음
        return "NO_SALES_30D", None, None
    avg = Fraction(sales_30d, SALES_WINDOW_DAYS)  # 추천과 같은 일평균
    return "OK", float(avg), round(float(available / avg), 1)  # 소진 예상일 = 가용재고 ÷ 일평균 (0 이면 0.0)


def cover_alert(product: Product, supplier: Supplier, result) -> str:
    """곧 소진 판정. SHORT = 발주 추천 대상(가용재고 ≤ 일평균 × 리드타임 + 안전재고), OK = 아님, UNKNOWN = 판정 못 함.

    품목·기본 공급업체가 비활성이면 새 발주를 못 하고 리드타임도 쓸 수 없어 UNKNOWN 이다(임의의 7일을 쓰지 않는다).
    예) 일평균 10, 리드타임 5, 안전재고 20 → 기준 70. 현재고 10 + 입고 예정 500 = 510 → OK, 현재고 50 → SHORT.
    """
    if not (product.is_active and supplier.is_active):
        return "UNKNOWN"
    return {"SHORTAGE": "SHORT", "NORMAL": "OK"}.get(stock_status(result), "UNKNOWN")  # 제외(데이터 부족·판매 없음)는 UNKNOWN


def trend_buckets(daily: dict[date, int], start: date, end: date, bucket: str) -> list[dict]:
    """차트용 추이. 판매 없는 날·주도 0 으로 채운다. 주 단위는 월~일이고 기간 양 끝 주는 기간 안쪽만 센다(start·end·days 로 표시).

    예) 기간 첫날이 일요일이면 첫 주는 그 하루(days 1), 오늘이 수요일이면 마지막 주는 월~수(days 3, 진행 중).
    """
    rows, day = [], start
    while day <= end:
        last = min(end, day + timedelta(days=6 - day.weekday())) if bucket == "week" else day  # 그 주 일요일 또는 그날
        qty = sum(daily.get(day + timedelta(days=i), 0) for i in range((last - day).days + 1))
        rows.append({"start": day.isoformat(), "end": last.isoformat(), "days": (last - day).days + 1, "quantity": qty})
        day = last + timedelta(days=1)
    return rows


def get_sales_analytics(company_id: int, db: Session, today: date, days: int, bucket: str) -> dict:
    """GET /sales-analytics 응답 본문. 기간 = 오늘 포함 days 일(오늘−(days−1) ~ 오늘)."""
    start = today - timedelta(days=days - 1)
    period = net_sales_by(company_id, db, start, today, InventoryMovement.product_id)  # 품목 id → 기간 순판매
    daily = net_sales_by(company_id, db, start, today, InventoryMovement.movement_date)  # 판매 날짜 → 순판매
    sales_30d = net_sales(company_id, db, today)  # 품목 id → 30일 순판매 (추천과 같은 숫자)
    stocks = stock_and_first_day(company_id, db)  # 품목 id → (현재고, 첫 입출고 날짜)
    transit = in_transit(company_id, db)  # 품목 id → 입고 예정 (ORDERED 미입고, 추천과 같은 숫자)
    suppliers = {}  # 품목 id → 기본 공급업체
    products = []
    for product, supplier in db.execute(
        select(Product, Supplier).join(Supplier, Supplier.id == Product.default_supplier_id)  # 기본 공급업체는 필수
        .where(Product.company_id == company_id)  # 우리 회사 품목만 (R1)
    ).all():
        products.append(product)
        suppliers[product.id] = supplier

    shown = [p for p in products if p.is_active or period.get(p.id, 0) > 0]  # 비활성 품목은 기간에 판매가 있을 때만
    shown.sort(key=lambda p: (-period.get(p.id, 0), p.sku))  # 판매량 많은 순 (TOP N 은 화면이 앞에서 자른다), 같으면 SKU 순
    grades = abc_grades([period.get(p.id, 0) for p in shown])
    total = sum(period.values())
    items = []
    for product, grade in zip(shown, grades, strict=True):
        stock, first_day = stocks.get(product.id, (0, None))  # 이력이 없으면 재고 0, 첫 날짜 없음
        coming = transit.get(product.id, 0)
        available = available_stock(stock, coming)
        status, avg, days_left = cover(today, first_day, sales_30d.get(product.id, 0), available)
        supplier = suppliers[product.id]
        result = calculate_recommendation(  # 추천 목록과 같은 함수·같은 입력 (박스·최소 주문량은 추천 여부를 바꾸지 않아 생략)
            today=today, first_movement_date=first_day, supplier_active=supplier.is_active,
            sales_30d=sales_30d.get(product.id, 0), stock=stock, in_transit=coming,
            lead_time=supplier.lead_time_days, safety_stock=product.safety_stock, unit=product.unit,
        )
        alert = cover_alert(product, supplier, result)
        qty = period.get(product.id, 0)
        items.append({
            "product_id": product.id, "product_sku": product.sku, "product_name": product.name,
            "color": product.color, "size": product.size, "spec": product.spec, "unit": product.unit,
            "is_active": product.is_active,
            "quantity": qty,  # 선택한 기간의 순판매
            "share": round(qty / total, 4) if total else 0.0,  # 기간 전체 판매에서 차지하는 비율 (0.4213 = 42.13%)
            "abc_grade": grade,  # A/B/C, 판매 없으면 null
            "sales_30d": sales_30d.get(product.id, 0),  # 최근 30일 순판매 (추천과 같은 숫자)
            "avg_daily_sales": avg,  # 일평균 (소수 그대로, 화면은 첫째 자리). 상태가 OK 가 아니면 null
            "current_stock": stock,
            "in_transit": coming,  # 입고 예정 (ORDERED 발주의 미입고)
            "available_stock": available,  # 가용재고 = 현재고 + 입고 예정
            "lead_time_days": supplier.lead_time_days if product.is_active and supplier.is_active else None,  # 발주 정보가 없으면 null
            "days_of_cover": days_left,  # 소진 예상일 = 가용재고 ÷ 일평균 (소수 첫째 자리). 상태가 OK 가 아니면 null
            "cover_alert": alert,  # SHORT(곧 소진 = 발주 추천 대상) / OK / UNKNOWN(판정 못 함)
            "cover_status": status,  # OK / NO_SALES_30D(판매 없음) / INSUFFICIENT_DATA(데이터 부족)
        })
    return {
        "period": {"start": start.isoformat(), "end": today.isoformat(), "days": days, "bucket": bucket},
        "basis": {"avg_window_days": SALES_WINDOW_DAYS, "min_history_days": MIN_HISTORY_DAYS},  # 일평균·데이터 부족 기준
        "source": SOURCE, "source_note": SOURCE_NOTE,
        "total_quantity": total,
        "trend": trend_buckets(daily, start, today, bucket),
        "items": items,
    }
