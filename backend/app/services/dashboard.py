"""대시보드 (F7). 읽기만 하는 요약 조회: 진행 중 발주, 이번 달 입출고, 장기재고, 부족·과잉재고. 저장·commit 은 하지 않는다.

부족·과잉은 추천 계산(calculate_for → calculate_recommendation)의 결과로만 판정한다(공식이 두 곳에 생기지 않게, #76).
모든 함수는 company_id 를 첫 번째 인자로 받고(R1), 오늘 날짜(today)는 인자로 받는다(테스트가 날짜를 고정할 수 있게).
"""

from datetime import date, timedelta  # 날짜, 날짜 빼기

from sqlalchemy import case, func, select  # 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session, aliased  # DB 세션 타입, 같은 표를 두 번 쓰기(정정 ↔ 원래 이력)

from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem  # 표
from app.services.purchase_orders import (
    received_quantities,  # 발주 줄별 누적 입고량 (한 번의 GROUP BY)
)
from app.services.recommend import (  # 과잉 기준(일), 과잉 판정, 부족 판정
    OVERSTOCK_DAYS,
    is_overstock,
    stock_status,
)
from app.services.recommendations import calculate_for  # 추천 계산 (쿼리 5번)

# 장기재고 기준: 현재고가 있는데 마지막 판매(정정 반영)가 오늘 − N일보다 이전. 임시값, 인터뷰 후 재검토 (CLAUDE.md §10)
DEAD_STOCK_DAYS = 60
LIST_LIMIT = 20  # 장기재고·부족·과잉 목록에서 화면에 보여줄 최대 줄 수 (전체 건수는 따로 센다)


def open_orders(company_id: int, db: Session) -> dict:
    """진행 중 발주: 상태별 건수(DRAFT·APPROVED·ORDERED)와 입고 예정 수량(ORDERED 발주의 미입고 합계). 조회 3번."""
    counts = dict(db.execute(
        select(PurchaseOrder.status, func.count()).where(
            PurchaseOrder.company_id == company_id,  # 우리 회사만 (R1)
            PurchaseOrder.status.in_(["DRAFT", "APPROVED", "ORDERED"]),  # RECEIVED·CANCELLED 는 끝난 발주
        ).group_by(PurchaseOrder.status)
    ).all())  # 상태 → 건수
    items = db.execute(
        select(PurchaseOrderItem.id, PurchaseOrderItem.quantity).join(
            PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id
        ).where(PurchaseOrder.company_id == company_id, PurchaseOrder.status == "ORDERED")  # 발주함 상태의 줄만
    ).all()  # (줄 id, 발주 수량)
    received = received_quantities(company_id, db, [i.id for i in items])  # 줄별 누적 입고량 (입고 − 정정)
    incoming = sum(i.quantity - received.get(i.id, 0) for i in items)  # 예) 발주 100 중 70 입고 → 30개가 들어오는 중
    return {
        "draft": counts.get("DRAFT", 0), "approved": counts.get("APPROVED", 0), "ordered": counts.get("ORDERED", 0),
        "incoming_quantity": incoming,
    }


def month_movements(company_id: int, db: Session, today: date) -> dict:
    """이번 달(1일~오늘) 입고·출고 수량. 정정은 원래 이력의 유형에서 뺀다(날짜도 원래 날짜). 조정은 입출고가 아니라 제외. 조회 1번."""
    orig = aliased(InventoryMovement)  # 정정이 가리키는 원래 이력
    kind = func.coalesce(orig.movement_type, InventoryMovement.movement_type)  # 정정이면 원래 유형, 아니면 자기 유형
    signed = case((InventoryMovement.movement_type == "CORRECTION", -InventoryMovement.quantity), else_=InventoryMovement.quantity)  # 정정은 −
    sums = dict(db.execute(
        select(kind, func.sum(signed))
        .select_from(InventoryMovement)
        .outerjoin(orig, orig.id == InventoryMovement.reverses_movement_id)  # 정정만 원래 이력이 붙는다
        .where(
            InventoryMovement.company_id == company_id,  # 우리 회사만 (R1)
            InventoryMovement.movement_date >= today.replace(day=1),  # 이번 달 1일부터
            InventoryMovement.movement_date <= today,  # 오늘까지
        ).group_by(kind)
    ).all())  # 유형 → 순수량. 예) SALE: 100 − 정정 90 = 10
    return {
        "in_quantity": int(sums.get("RECEIPT", 0)),  # 입고 = 발주·직접 입고
        "out_quantity": int(sum(sums.get(t, 0) for t in ("SALE", "DISPOSAL", "OTHER_OUT"))),  # 출고 = 판매·폐기·기타 출고
    }


def dead_stock(company_id: int, db: Session, today: date) -> dict:
    """장기재고: 활성 품목 중 현재고 > 0, 첫 입출고가 N일 이상 전, 마지막 순판매일이 오늘 − N일보다 이전(또는 판매 없음). 한 번의 쿼리.

    예) N=60, 오늘 11-04: 마지막 판매 09-05(정확히 60일 전)는 장기재고 아님, 09-04(61일 전)는 장기재고.
    순판매 = SALE 수량 − 그 SALE 을 가리키는 정정 합계 (PROGRESS 규칙). 전량 정정된 판매는 판매가 아니었던 것으로 본다.
    """
    limit_day = today - timedelta(days=DEAD_STOCK_DAYS)  # 이 날짜보다 이전이면 N일 넘게 안 팔린 것
    signed = case((InventoryMovement.direction == "IN", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # IN +, OUT −
    stock = (
        select(  # 품목별 현재고와 첫 입출고일
            InventoryMovement.product_id, func.sum(signed).label("stock"), func.min(InventoryMovement.movement_date).label("first_day"),
        ).where(InventoryMovement.company_id == company_id).group_by(InventoryMovement.product_id).subquery()
    )
    corrected = (
        select(InventoryMovement.reverses_movement_id.label("original_id"), func.sum(InventoryMovement.quantity).label("qty"))  # 판매별 정정 합계
        .where(InventoryMovement.company_id == company_id, InventoryMovement.reverses_movement_id.is_not(None))
        .group_by(InventoryMovement.reverses_movement_id).subquery()
    )
    sale = aliased(InventoryMovement)  # 판매 이력
    last_sale = (
        select(sale.product_id, func.max(sale.movement_date).label("last_sale_date"))  # 품목별 마지막 순판매일
        .outerjoin(corrected, corrected.c.original_id == sale.id)
        .where(
            sale.company_id == company_id, sale.movement_type == "SALE",
            sale.quantity - func.coalesce(corrected.c.qty, 0) > 0,  # 정정 뒤에도 판매가 남은 것만
        ).group_by(sale.product_id).subquery()
    )
    rows = db.execute(
        select(Product, stock.c.stock, last_sale.c.last_sale_date, func.count().over().label("total"))  # total: 자르기 전 전체 건수
        .join(stock, stock.c.product_id == Product.id)  # 이력이 없는 품목은 현재고 0이라 빠진다
        .outerjoin(last_sale, last_sale.c.product_id == Product.id)  # 판매가 없으면 NULL
        .where(
            Product.company_id == company_id, Product.is_active.is_(True),  # 우리 회사, 비활성 제외
            stock.c.stock > 0,  # 재고가 있어야 장기재고
            stock.c.first_day <= limit_day,  # 첫 입출고가 N일 이내인 신규 품목은 제외
            (last_sale.c.last_sale_date.is_(None)) | (last_sale.c.last_sale_date < limit_day),  # 판매가 없거나 N일 넘게 전
        ).order_by(stock.c.stock.desc(), Product.id).limit(LIST_LIMIT)  # 재고 많은 순
    ).all()
    return {
        "days": DEAD_STOCK_DAYS,
        "count": rows[0].total if rows else 0,  # 전체 건수 (화면에 보이는 줄 수와 다를 수 있다)
        "items": [
            {"product_id": r.Product.id, "sku": r.Product.sku, "name": r.Product.name, "unit": r.Product.unit,
             "current_stock": int(r.stock), "last_sale_date": r.last_sale_date}  # 판매가 없으면 None
            for r in rows
        ],
    }


def shortage_and_overstock(company_id: int, db: Session, today: date) -> dict:
    """부족(추천 대상)과 과잉(현재고 ≥ 일평균 × 90일) 품목. 활성 품목만, 최신 품목 먼저, 목록은 20줄까지.

    장기재고와는 겹치지 않는다: 과잉은 최근 30일 판매가 있어야 하고, 장기재고는 60일 넘게 판매가 없어야 한다.
    """
    shortage, overstock = [], []  # 부족 품목, 과잉 품목
    for product, _, stock, _, result in calculate_for(company_id, db, today):  # 추천 목록과 같은 계산 하나
        base = {"product_id": product.id, "sku": product.sku, "name": product.name, "unit": product.unit, "current_stock": stock}
        if stock_status(result) == "SHORTAGE":  # 예) 가용재고 50 ≤ 재주문점 70
            shortage.append({**base, "available": result.available, "reorder_point": float(result.reorder_point),
                             "recommended_quantity": result.recommended_quantity})
        if is_overstock(stock, result):  # 예) 현재고 900 ≥ 10 × 90
            overstock.append({**base, "avg_daily_sales": float(result.avg_daily_sales)})
    return {
        "shortage": {"count": len(shortage), "items": shortage[:LIST_LIMIT]},  # 전체 건수와 앞 20줄
        "overstock": {"days": OVERSTOCK_DAYS, "count": len(overstock), "items": overstock[:LIST_LIMIT]},
    }


def get_dashboard(company_id: int, db: Session, today: date) -> dict:
    """GET /dashboard 응답 본문. 쿼리는 품목 수와 무관하다(장기재고 1번 + 추천 계산 5번 + 그 밖)."""
    return {
        **shortage_and_overstock(company_id, db, today),  # shortage, overstock (#76)
        "purchase_orders": open_orders(company_id, db),
        "month": {"month_start": today.replace(day=1), **month_movements(company_id, db, today)},
        "dead_stock": dead_stock(company_id, db, today),
    }
