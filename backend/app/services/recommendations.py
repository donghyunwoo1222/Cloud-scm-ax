"""추천 조회 service (F8, #39). 조회만 하고, 계산은 #38 의 순수 함수 calculate_recommendation 하나로 한다.

읽기만 하므로 저장·commit 하지 않는다. 쿼리는 품목 수와 상관없이 5번(품목, 현재고·첫 입출고, 30일 순판매, ORDERED 줄, 누적 입고).
회사는 company_id 인자로만 받고(R1, 토큰에서), 오늘 날짜(today)도 인자로 받는다(테스트가 날짜를 고정할 수 있게).
"""

from datetime import date, timedelta  # 날짜, 날짜 빼기

from sqlalchemy import case, func, select  # 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from app.services.purchase_orders import (
    received_quantities,  # 발주 줄별 누적 입고량 (입고 − 입고 정정)
)
from app.services.recommend import (  # 추천 계산 순수 함수와 결과 모양 (#38)
    SALES_WINDOW_DAYS,
    Excluded,
    calculate_recommendation,
)


def stock_and_first_day(company_id: int, db: Session) -> dict[int, tuple[int, date]]:
    """품목별 (현재고, 첫 입출고 날짜). 한 번의 GROUP BY. 이력이 없는 품목은 키가 없다(erd.md 조회 1, 그 밖의 조회)."""
    signed = case((InventoryMovement.direction == "IN", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # IN +, OUT −
    return {pid: (int(stock), first) for pid, stock, first in db.execute(
        select(InventoryMovement.product_id, func.sum(signed), func.min(InventoryMovement.movement_date))  # 현재고, 첫 날짜 (정정 포함 모든 유형)
        .where(InventoryMovement.company_id == company_id)  # 우리 회사만 (R1)
        .group_by(InventoryMovement.product_id)
    ).all()}  # 예) 입고 320 − 판매 300 − 폐기 5 = 15


def net_sales(company_id: int, db: Session, today: date) -> dict[int, int]:
    """품목별 최근 30일 순판매 = 기간 안 SALE − 그 SALE 을 가리키는 정정 합계 (erd.md 조회 2). 한 번의 쿼리. 판매가 없으면 키 없음.

    기간은 오늘 포함 30일(오늘−29일 ~ 오늘)이고 원래 SALE 의 날짜로 판단한다. 폐기·조정의 정정은 SALE 에 붙지 않아 빼지 않는다.
    예) 오늘 11-04: 10-06 판매는 포함(오늘−29일), 10-05 판매는 제외(오늘−30일). SALE 100 + 정정 90 → 10 (S13).
    """
    corrected = (
        select(InventoryMovement.reverses_movement_id.label("original_id"), func.sum(InventoryMovement.quantity).label("qty"))  # 원래 이력별 정정 합계
        .where(InventoryMovement.company_id == company_id, InventoryMovement.movement_type == "CORRECTION")
        .group_by(InventoryMovement.reverses_movement_id).subquery()
    )
    return {pid: int(qty) for pid, qty in db.execute(
        select(InventoryMovement.product_id, func.sum(InventoryMovement.quantity - func.coalesce(corrected.c.qty, 0)))  # SALE마다 (수량 − 정정)
        .outerjoin(corrected, corrected.c.original_id == InventoryMovement.id)  # 정정을 원래 SALE 에 붙인다
        .where(
            InventoryMovement.company_id == company_id,  # 우리 회사만 (R1)
            InventoryMovement.movement_type == "SALE",  # 판매만 (폐기·기타 출고·조정 제외)
            InventoryMovement.movement_date >= today - timedelta(days=SALES_WINDOW_DAYS - 1),  # 오늘−29일부터
            InventoryMovement.movement_date <= today,  # 오늘까지
        ).group_by(InventoryMovement.product_id)
    ).all()}


def in_transit(company_id: int, db: Session) -> dict[int, int]:
    """품목별 발주 진행 중 수량 = ORDERED 발주 줄의 (발주 수량 − 누적 입고량) 합계 (erd.md 조회 3). 쿼리 2번.

    DRAFT·APPROVED 는 아직 주문 전, RECEIVED·CANCELLED 는 더 오지 않으므로 넣지 않는다(S4). 예) 100 중 40 입고 → 60.
    """
    lines = db.execute(
        select(PurchaseOrderItem.id, PurchaseOrderItem.product_id, PurchaseOrderItem.quantity)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)  # 줄이 속한 발주서의 상태를 보려고
        .where(PurchaseOrder.company_id == company_id, PurchaseOrder.status == "ORDERED")  # 우리 회사의 발주함 상태만
    ).all()  # (줄 id, 품목 id, 발주 수량)
    received = received_quantities(company_id, db, [line.id for line in lines])  # 줄별 누적 입고량 (한 번의 GROUP BY)
    totals: dict[int, int] = {}  # 품목 id → 미입고 합계
    for line in lines:
        totals[line.product_id] = totals.get(line.product_id, 0) + line.quantity - received.get(line.id, 0)  # 줄마다 미입고를 더한다
    return totals


def list_recommendations(company_id: int, db: Session, today: date) -> dict:
    """GET /recommendations 응답 본문: items(추천)와 excluded(계산하지 않은 품목). 활성 품목만, 최신 품목 먼저. 저장하지 않는다."""
    products = db.execute(
        select(Product, Supplier).join(Supplier, Supplier.id == Product.default_supplier_id)  # 품목과 기본 공급업체(리드타임·활성)
        .where(Product.company_id == company_id, Product.is_active.is_(True))  # 우리 회사, 비활성 품목은 추천 목록에 안 나온다
        .order_by(Product.id.desc())  # 목록 공통 규칙: 최신순
    ).all()
    stocks = stock_and_first_day(company_id, db)  # 품목 id → (현재고, 첫 입출고 날짜)
    sales = net_sales(company_id, db, today)  # 품목 id → 30일 순판매
    transit = in_transit(company_id, db)  # 품목 id → 진행 중 발주 수량
    items, excluded = [], []  # 추천 목록, 제외 목록
    for product, supplier in products:
        stock, first_day = stocks.get(product.id, (0, None))  # 이력이 없으면 현재고 0, 첫 날짜 없음
        result = calculate_recommendation(  # 공식은 이 함수 한 곳에만 있다
            today=today, first_movement_date=first_day, supplier_active=supplier.is_active,
            sales_30d=sales.get(product.id, 0), stock=stock, in_transit=transit.get(product.id, 0),
            lead_time=supplier.lead_time_days, safety_stock=product.safety_stock,
        )
        if isinstance(result, Excluded):  # 제외: 코드와 안내 문장
            excluded.append({"product_id": product.id, "product_sku": product.sku, "product_name": product.name,
                             "code": result.code, "message": result.message})
        elif result.recommended_quantity is not None:  # 추천: 가용재고 ≤ 재주문점 (충분한 품목은 어느 목록에도 넣지 않는다)
            items.append({
                "product_id": product.id, "product_sku": product.sku, "product_name": product.name,
                "supplier_id": supplier.id, "supplier_name": supplier.name,
                "current_stock": stock, "in_transit": transit.get(product.id, 0), "available": result.available,
                "avg_daily_sales": float(result.avg_daily_sales),  # 분수 → 소수 그대로 (예: 7/30 → 0.2333…). 표시는 화면이 첫째 자리로
                "lead_time_days": supplier.lead_time_days, "safety_stock": product.safety_stock,
                "reorder_point": float(result.reorder_point),  # 예: 70.0, 19/6 → 3.1666…
                "recommended_quantity": result.recommended_quantity, "reason": result.reason,
            })
    return {"items": items, "excluded": excluded}
