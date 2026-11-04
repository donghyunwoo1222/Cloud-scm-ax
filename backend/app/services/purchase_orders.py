"""발주서 작성·수정·조회 (F6, #33). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1).

저장 확정(commit)은 하지 않는다. API 경로 함수가 요청 끝에 한 번만 한다.
"""

from collections import defaultdict  # 없는 키는 빈 목록으로 시작하는 딕셔너리

from sqlalchemy import case, delete, func, select  # 삭제, 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 공통 오류
from app.models import (  # 표들
    Company,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.purchase_orders import (  # 요청·응답 모양
    ItemIn,
    ItemOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
)
from app.services.tenant import check_ref, get_owned, scoped  # 회사 분리 도우미 (#23)


def inactive(field: str, message: str) -> AppError:
    return AppError(409, "INACTIVE_REFERENCE", message, [{"field": field, "reason": "inactive"}])  # 비활성은 새 발주에 못 쓴다


def check_items(company_id: int, db: Session, items: list[ItemIn], keep: set[int]) -> dict[int, Product]:
    """품목 줄 검사: 같은 품목 두 줄이면 409 DUPLICATE_ITEM, 다른 회사 품목이면 404, 새로 넣는 비활성 품목이면 409.

    keep 은 이미 발주서에 있던 품목 id. 나중에 비활성이 된 품목은 줄을 유지할 수 있다(승인 때 막는다, #34).
    """
    ids = [i.product_id for i in items]  # 요청의 품목 번호들
    if len(set(ids)) != len(ids):  # 같은 품목이 두 번 들어 있으면
        raise AppError(409, "DUPLICATE_ITEM", "같은 품목을 두 번 넣을 수 없습니다. 수량을 한 줄로 합쳐 주세요.",
                       [{"field": "items", "reason": "duplicate"}])
    products = {}  # 품목 id → 품목
    for product_id in ids:
        product = check_ref(company_id, db, Product, product_id, "items")  # 다른 회사·없는 id 는 404
        if not product.is_active and product_id not in keep:  # 새로 넣는 줄이 비활성이면
            raise inactive("items", f"비활성 품목({product.sku})은 발주에 넣을 수 없습니다.")
        products[product_id] = product
    return products


def next_po_number(company_id: int, db: Session) -> str:
    """발주번호 = PO-서울 오늘 날짜-그날 회사의 발주 순번 (예: PO-20261104-003). 호출한 쪽이 회사 행을 잠근 상태여야 순번이 안 겹친다."""
    prefix = f"PO-{seoul_today():%Y%m%d}-"  # 예) PO-20261104-
    count = db.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.company_id == company_id, PurchaseOrder.po_number.startswith(prefix)))  # 오늘 이미 만든 수
    return f"{prefix}{count + 1:03d}"  # 예) 2장 있으면 003


def create_order(company_id: int, db: Session, user_id: int, data: PurchaseOrderCreate) -> PurchaseOrder:
    """POST /purchase-orders: DRAFT 한 장 만들기. 공급업체당 DRAFT 는 하나(409 DUPLICATE_DRAFT)."""
    supplier = check_ref(company_id, db, Supplier, data.supplier_id, "supplier_id")  # 다른 회사·없는 id 는 404
    if not supplier.is_active:  # 비활성 업체는 새 발주에 못 쓴다
        raise inactive("supplier_id", "비활성 공급업체에는 새 발주서를 만들 수 없습니다.")
    check_items(company_id, db, data.items, keep=set())  # 품목 줄 검사
    db.execute(select(Company.id).where(Company.id == company_id).with_for_update())  # 회사 행 잠금: 같은 회사의 동시 작성이 한 줄로 서서 발주번호·DRAFT 검사가 안 겹친다
    draft = db.scalar(scoped(company_id, PurchaseOrder).where(
        PurchaseOrder.supplier_id == supplier.id, PurchaseOrder.status == "DRAFT"))  # 이 업체의 기존 DRAFT
    if draft is not None:
        raise AppError(
            409, "DUPLICATE_DRAFT",
            f"이 공급업체에 작성 중인 발주서({draft.po_number})가 이미 있습니다. 그 발주서에 품목을 추가하세요.",
            {"purchase_order_id": draft.id, "po_number": draft.po_number},  # 화면이 기존 초안으로 안내할 수 있게
        )
    order = PurchaseOrder(
        company_id=company_id, supplier_id=supplier.id, po_number=next_po_number(company_id, db),
        due_date=data.due_date, memo=data.memo, created_by=user_id,  # 상태는 DB 기본값 DRAFT
    )
    db.add(order)
    db.flush()  # 발주서 id 받기 (확정은 아직)
    db.add_all(PurchaseOrderItem(company_id=company_id, purchase_order_id=order.id, **i.model_dump()) for i in data.items)  # 품목 줄
    db.flush()
    return order


def update_order(company_id: int, db: Session, order_id: int, data: PurchaseOrderUpdate) -> PurchaseOrder:
    """PATCH /purchase-orders/{id}: DRAFT 일 때만(409 INVALID_STATUS). items 를 보내면 최종 목록으로 맞춘다."""
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # 발주서 잠금(잠금 순서: 발주서 → 품목). 다른 회사 404
    if order.status != "DRAFT":  # 승인 이후에는 수정 불가 (R5)
        raise AppError(409, "INVALID_STATUS", "작성 중(DRAFT)인 발주서만 수정할 수 있습니다.", {"status": order.status})
    if data.items is not None:  # 품목 줄을 보냈으면
        existing = {i.product_id: i for i in db.scalars(scoped(company_id, PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id == order.id))}  # 지금 줄들 (품목 id → 줄)
        check_items(company_id, db, data.items, keep=set(existing))  # 검사: 새로 넣는 줄만 활성 필요
        wanted = {i.product_id for i in data.items}
        gone = [i.id for pid, i in existing.items() if pid not in wanted]  # 목록에서 빠진 줄
        if gone:
            db.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(gone)))  # 삭제 (DRAFT 줄은 입고 이력이 없다)
        for item in data.items:
            if item.product_id in existing:  # 있던 줄은 수량·단가만 바꾼다 (추천 근거는 유지)
                existing[item.product_id].quantity = item.quantity
                existing[item.product_id].unit_price = item.unit_price
            else:  # 새 줄
                db.add(PurchaseOrderItem(company_id=company_id, purchase_order_id=order.id, **item.model_dump()))
    for field, value in data.model_dump(exclude_unset=True, exclude={"items"}).items():  # 납기·메모 중 보낸 칸 (줄 검사를 모두 통과한 뒤에 바꾼다)
        setattr(order, field, value)
    db.flush()
    return order


def get_order(company_id: int, db: Session, order_id: int) -> PurchaseOrder:
    return get_owned(company_id, db, PurchaseOrder, order_id)  # 다른 회사·없는 id 는 404


def list_orders(company_id: int, db: Session, page: PageParams, supplier_id: int | None) -> tuple[list[PurchaseOrder], dict]:
    """GET /purchase-orders: 최신순, supplier_id 로 공급업체별 조회."""
    stmt = scoped(company_id, PurchaseOrder)  # 회사 조건이 붙은 시작점
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)  # 이 업체 발주만 (남의 업체 id 면 빈 목록)
    return paginate(db, stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()), page)


def build_out(company_id: int, db: Session, orders: list[PurchaseOrder]) -> list[dict]:
    """발주서들을 응답 모양으로. 줄·품목·업체·누적 입고량을 목록 전체에 대해 각각 한 번의 조회로 가져온다(N+1 없음)."""
    ids = [o.id for o in orders]
    items = list(db.scalars(scoped(company_id, PurchaseOrderItem).where(
        PurchaseOrderItem.purchase_order_id.in_(ids)).order_by(PurchaseOrderItem.id))) if ids else []  # 모든 줄
    products = {p.id: p for p in db.scalars(scoped(company_id, Product).where(
        Product.id.in_({i.product_id for i in items})))} if items else {}  # 품목 id → 품목
    suppliers = {s.id: s for s in db.scalars(scoped(company_id, Supplier).where(
        Supplier.id.in_({o.supplier_id for o in orders})))} if orders else {}  # 업체 id → 업체
    signed = case((InventoryMovement.movement_type == "RECEIPT", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # 입고 +, 정정 −
    received = dict(db.execute(
        select(InventoryMovement.purchase_order_item_id, func.sum(signed)).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.purchase_order_item_id.in_([i.id for i in items]),  # 발주에 연결된 이력만 (입고와 그 정정)
        ).group_by(InventoryMovement.purchase_order_item_id)
    ).all()) if items else {}  # 줄 id → 누적 입고량
    by_order = defaultdict(list)  # 발주서 id → 줄 응답들
    for i in items:
        p = products[i.product_id]
        by_order[i.purchase_order_id].append(ItemOut(
            id=i.id, product_id=i.product_id, product_sku=p.sku, product_name=p.name, quantity=i.quantity,
            unit_price=i.unit_price, recommended_quantity=i.recommended_quantity,
            recommendation_reason=i.recommendation_reason, received_quantity=int(received.get(i.id, 0)),
        ))
    return [
        PurchaseOrderOut(
            **{c: getattr(o, c) for c in PurchaseOrderOut.model_fields if c not in ("supplier_name", "items")},
            supplier_name=suppliers[o.supplier_id].name, items=by_order[o.id],
        ).model_dump(mode="json")
        for o in orders
    ]
