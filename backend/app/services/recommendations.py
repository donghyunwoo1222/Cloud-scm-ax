"""추천 조회(#39)와 추천으로 초안 만들기(#40) service (F8). 계산은 #38 의 순수 함수 calculate_recommendation 하나로 한다.

조회는 저장하지 않고, 초안 만들기도 commit 하지 않는다(API 경로 함수가 요청 끝에 한 번만). 쿼리는 품목 수와 상관없이 5번(품목, 현재고·첫 입출고, 30일 순판매, ORDERED 줄, 누적 입고).
회사는 company_id 인자로만 받고(R1, 토큰에서), 오늘 날짜(today)도 인자로 받는다(테스트가 날짜를 고정할 수 있게).
"""

from collections import defaultdict  # 없는 키는 빈 목록으로 시작하는 딕셔너리
from datetime import date, timedelta  # 날짜, 날짜 빼기

from sqlalchemy import case, func, select  # 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.errors import AppError  # 공통 오류
from app.models import (  # 표
    Company,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.schemas.recommendations import DraftCreate  # 초안 만들기 요청 모양
from app.services.products import (
    filter_product_search,  # 재고 목록과 품목 목록이 같은 이름·SKU 검색을 쓴다
)
from app.services.purchase_orders import (
    check_items,  # 요청 품목 검사: 같은 품목 두 줄 409, 다른 회사 404, 비활성 품목 409
    inactive,  # 409 INACTIVE_REFERENCE 오류
    next_po_number,  # 발주번호 (회사 행을 잠근 뒤에 불러야 순번이 안 겹친다)
    order_item_values,  # 수동 발주와 같은 박스 환산·상한 검사
    received_quantities,  # 발주 줄별 누적 입고량 (입고 − 입고 정정)
)
from app.services.recommend import (  # 추천 계산 순수 함수와 결과 모양 (#38)
    SALES_WINDOW_DAYS,
    Excluded,
    calculate_recommendation,
)
from app.services.tenant import scoped  # 회사 조건이 붙은 SELECT


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


def calculate_for(
    company_id: int, db: Session, today: date, product_ids: list[int] | None = None,
    *, q: str | None = None,  # 재고 상태를 계산하기 전에 검색어로 품목을 좁힐 수 있다
    group_code: str | None = None,  # 그룹 코드로도 좁힐 수 있다
) -> list[tuple]:
    """활성 품목마다 (품목, 기본 공급업체, 현재고, 진행 중 수량, 계산 결과). 최신 품목 먼저. 쿼리는 품목 수와 무관하게 5번.

    product_ids 를 주면 그 품목들만(추천 초안 #40), 없으면 회사의 모든 활성 품목(추천 목록 #39).
    """
    stmt = (
        select(Product, Supplier).join(Supplier, Supplier.id == Product.default_supplier_id)  # 품목과 기본 공급업체(리드타임·활성)
        .where(Product.company_id == company_id, Product.is_active.is_(True))  # 우리 회사, 비활성 품목은 추천에 안 나온다
        .order_by(Product.id.desc())  # 목록 공통 규칙: 최신순
    )
    if product_ids is not None:
        stmt = stmt.where(Product.id.in_(product_ids))  # 요청한 품목만
    products = db.execute(filter_product_search(stmt, q, group_code)).all()  # 이름·SKU가 일치하는 활성 품목만 계산 대상으로 가져온다
    stocks = stock_and_first_day(company_id, db)  # 품목 id → (현재고, 첫 입출고 날짜)
    sales = net_sales(company_id, db, today)  # 품목 id → 30일 순판매
    transit = in_transit(company_id, db)  # 품목 id → 진행 중 발주 수량
    rows = []
    for product, supplier in products:
        stock, first_day = stocks.get(product.id, (0, None))  # 이력이 없으면 현재고 0, 첫 날짜 없음
        result = calculate_recommendation(  # 공식은 이 함수 한 곳에만 있다
            today=today, first_movement_date=first_day, supplier_active=supplier.is_active,
            sales_30d=sales.get(product.id, 0), stock=stock, in_transit=transit.get(product.id, 0),
            lead_time=supplier.lead_time_days, safety_stock=product.safety_stock, unit=product.unit,
            unit_factor=product.units_per_box or 1, order_unit=product.order_unit,  # 발주단위 올림 (#187)
            min_order_units=product.min_order_units,  # 최소 주문량까지 올림 (#194)
        )
        rows.append((product, supplier, stock, transit.get(product.id, 0), result))
    return rows


def list_recommendations(company_id: int, db: Session, today: date) -> dict:
    """GET /recommendations 응답 본문: items(추천)와 excluded(계산하지 않은 품목). 활성 품목만, 최신 품목 먼저. 저장하지 않는다."""
    items, excluded = [], []  # 추천 목록, 제외 목록
    for product, supplier, stock, transit_qty, result in calculate_for(company_id, db, today):
        if isinstance(result, Excluded):  # 제외: 코드와 안내 문장
            excluded.append({"product_id": product.id, "product_sku": product.sku, "product_name": product.name,
                             "color": product.color, "size": product.size, "spec": product.spec, "group_code": product.group_code,
                             "code": result.code, "message": result.message})
        elif result.recommended_quantity is not None:  # 추천: 가용재고 ≤ 재주문점 (충분한 품목은 어느 목록에도 넣지 않는다)
            items.append({
                "product_id": product.id, "product_sku": product.sku, "product_name": product.name,
                "color": product.color, "size": product.size, "spec": product.spec, "group_code": product.group_code,
                "supplier_id": supplier.id, "supplier_name": supplier.name, "unit": product.unit,
                "current_stock": stock, "in_transit": transit_qty, "available": result.available,
                "avg_daily_sales": float(result.avg_daily_sales),  # 분수 → 소수 그대로 (예: 7/30 → 0.2333…). 표시는 화면이 첫째 자리로
                "lead_time_days": supplier.lead_time_days, "safety_stock": product.safety_stock,
                "reorder_point": float(result.reorder_point),  # 예: 70.0, 19/6 → 3.1666…
                "recommended_quantity": result.recommended_quantity, "reason": result.reason,
                "units_per_box": product.units_per_box, "box_unit_cost": product.box_unit_cost,
                "order_unit": product.order_unit or product.unit, "unit_factor": product.units_per_box or 1,  # #185
                "recommended_order_units": result.order_units,  # 발주단위 수 (예: 230개, 1박스=100 → 3, #187)
                "recommended_arrival_quantity": result.arrival_quantity,  # 도착 수량(기본단위, 예: 300)
                "min_order_units": product.min_order_units,  # 최소 주문량 (#194)
                "moq_applied": result.moq_applied,  # 최소 주문량 때문에 늘어났는지 (화면 배지)
                "recommended_box_quantity": result.order_units if product.units_per_box is not None else None,  # 기존 칸 유지
            })
    return {"items": items, "excluded": excluded}


def create_drafts(company_id: int, db: Session, user_id: int, today: date, data: DraftCreate) -> list[tuple[PurchaseOrder, bool]]:
    """POST /recommendations/drafts: 품목들을 공급업체별 DRAFT 1장에 담는다. (발주서, 새로 만들었는지) 목록을 돌려준다.

    ① 잠금(회사 → 회사의 DRAFT 발주서들 → 요청 품목, 잠금 순서 규칙) → ② 요청 검사 → ③ 추천을 서버가 다시 계산
    (화면이 보낸 추천 수량은 받지 않는다) → ④ 공급업체마다 기존 DRAFT 에 품목 추가(created: false), 없으면 새로 만들기(created: true).
    잠근 **뒤에** 검사·계산한다(#84): 계산과 저장 사이에 그 품목의 입고·비활성 변경이 끼어들 수 없다(그런 요청은 품목 잠금을 기다린다).
    하나라도 막히면 409 로 끝나고, commit 전이라 앞에서 만든 초안도 함께 취소된다.
    """
    db.execute(select(Company.id).where(Company.id == company_id).with_for_update())  # ① 회사 행 잠금: 동시 요청이 한 줄로 서서 업체당 DRAFT 1장·발주번호가 안 겹친다
    drafts = {o.supplier_id: o for o in db.scalars(scoped(company_id, PurchaseOrder).where(
        PurchaseOrder.status == "DRAFT").order_by(PurchaseOrder.id).with_for_update())}  # 회사의 DRAFT 를 번호 순으로 잠금 (업체당 1장이라 많지 않다)
    check_items(company_id, db, data.items, keep=set(), lock=True)  # ① 품목 번호 순 잠금 → ② 같은 품목 두 줄 409, 다른 회사 404, 비활성 품목 409 (최신 값)
    requested = {i.product_id: i for i in data.items}  # 품목 id → 요청 줄
    rows = calculate_for(company_id, db, today, list(requested))  # ③ 잠근 뒤 조회 5번 + 순수 함수로 다시 계산
    not_recommended = []  # 지금은 추천 대상이 아닌 품목들
    for product, supplier, _, _, result in rows:
        if not supplier.is_active:  # 기본 공급업체가 비활성이면 새 발주에 못 쓴다 (MISSING_INFO 와 같은 경우)
            raise inactive("items", f"품목({product.sku})의 기본 공급업체({supplier.name})가 비활성이라 초안을 만들 수 없습니다.")
        if isinstance(result, Excluded) or result.recommended_quantity is None:  # 제외(데이터 부족·판매 없음) 또는 재고 충분
            not_recommended.append({"field": "items", "product_id": product.id, "sku": product.sku,
                                    "reason": result.code if isinstance(result, Excluded) else "ENOUGH_STOCK"})
    if not_recommended:  # 목록을 본 뒤 입고 등으로 바뀐 경우 (예: 가용재고 50 → 200 > 재주문점 70). 사용자 결정: 전체 거절
        raise AppError(409, "NOT_RECOMMENDED",
                       f"지금은 추천 대상이 아닌 품목이 있습니다({', '.join(n['sku'] for n in not_recommended)}). 추천 목록을 새로 불러오세요.",
                       not_recommended)

    by_supplier = defaultdict(list)  # 공급업체 id → [(품목, 계산 결과, 환산한 발주 칸)]
    suppliers = {}  # 공급업체 id → 공급업체
    for product, supplier, _, _, result in rows:
        line = requested[product.id]
        box_quantity = line.box_quantity
        if line.quantity is None and box_quantity is None:  # 수량 생략 시 박스 기본값을 서버가 다시 계산한다
            if product.units_per_box is None:
                raise AppError(422, "VALIDATION_ERROR", "박스 입수가 없는 품목에는 quantity를 보내세요.")
            box_quantity = result.order_units  # 순수 함수가 올림한 발주단위 수 (#187)
        values = order_item_values(product, line.quantity, product.unit_cost, box_quantity)
        by_supplier[supplier.id].append((product, result, values))
        suppliers[supplier.id] = supplier
    out = []  # (발주서, 새로 만들었는지)
    for supplier_id in sorted(by_supplier):  # ④ 공급업체 번호 순으로 처리
        supplier, lines = suppliers[supplier_id], by_supplier[supplier_id]
        order = drafts.get(supplier_id)  # 이 업체의 기존 DRAFT (①에서 잠근 것. 새 DRAFT 는 회사 잠금 없이 생기지 않는다)
        created = order is None  # 없으면 새로 만든다 (S9), 있으면 품목만 추가 (S10)
        if created:
            order = PurchaseOrder(
                company_id=company_id, supplier_id=supplier_id, po_number=next_po_number(company_id, db),
                due_date=today + timedelta(days=supplier.lead_time_days),  # 예상 납기 = 오늘 + 리드타임 (예: 11-04 + 5일 = 11-09)
                created_by=user_id,  # 상태는 DB 기본값 DRAFT
                payment_terms=supplier.payment_terms,  # 공급업체 기본 지불조건 복사 (#157)
            )
            db.add(order)
            db.flush()  # 발주서 id 받기 (확정은 아직)
        else:
            existing = set(db.scalars(select(PurchaseOrderItem.product_id).where(
                PurchaseOrderItem.purchase_order_id == order.id)))  # 이 초안에 이미 있는 품목들
            dup = [p.sku for p, _, _ in lines if p.id in existing]
            if dup:  # 같은 품목은 한 발주서에 한 줄 (같은 요청을 두 번 보낸 경우도 여기서 막힌다)
                raise AppError(409, "DUPLICATE_ITEM",
                               f"작성 중인 발주서({order.po_number})에 이미 있는 품목입니다({', '.join(dup)}). 그 발주서에서 수량을 고치세요.",
                               {"purchase_order_id": order.id, "po_number": order.po_number, "skus": dup})
        db.add_all(PurchaseOrderItem(
            company_id=company_id, purchase_order_id=order.id, product_id=p.id,
            **values,  # 환산한 발주 수량·단가와 필요한 경우 박스 정보
            recommended_quantity=r.recommended_quantity, recommendation_reason=r.reason,  # 서버가 다시 계산한 추천 근거 (예: 160)
        ) for p, r, values in lines)
        db.flush()  # DB 에 보낸다 (같은 품목 두 줄이면 고유 제약이 마지막 방어)
        out.append((order, created))
    return out
