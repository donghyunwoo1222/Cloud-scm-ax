"""발주서 작성·수정·조회(#33), 상태 변경 approve·order·cancel(#34), 발주 입고(#35) (F6). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1).

저장 확정(commit)은 하지 않는다. API 경로 함수가 요청 끝에 한 번만 한다.
"""

from collections import defaultdict  # 없는 키는 빈 목록으로 시작하는 딕셔너리
from collections.abc import Sequence  # 발주 줄과 추천 초안 줄을 공통으로 검사한다
from datetime import date, datetime, time, timedelta  # 납기 비교와 입고 시각

from sqlalchemy import case, delete, func, select  # 삭제, 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL, seoul_today  # 서울 시간대, 서울 기준 오늘
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
from app.schemas.common import MAX_QUANTITY  # 환산 후에도 기존 재고 단위 상한 적용
from app.schemas.purchase_orders import (  # 요청·응답 모양
    ItemIn,
    ItemOut,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
    ReceiptCreate,
    ReceiptDue,
)
from app.schemas.recommendations import DraftItemIn  # 추천 초안의 요청 줄
from app.services.stock import register_movement  # 이력을 쓰는 유일한 함수 (품목 잠금·flush)
from app.services.tenant import (  # 회사 분리 도우미 (#23), 404 문장
    NOT_FOUND_MESSAGE,
    check_ref,
    get_owned,
    scoped,
)


def inactive(field: str, message: str) -> AppError:
    return AppError(409, "INACTIVE_REFERENCE", message, [{"field": field, "reason": "inactive"}])  # 비활성은 새 발주에 못 쓴다


def check_items(
    company_id: int, db: Session, items: Sequence[ItemIn | DraftItemIn],
    keep: set[int], lock: bool = False,
) -> dict[int, Product]:
    """품목 줄 검사: 같은 품목 두 줄이면 409 DUPLICATE_ITEM, 다른 회사 품목이면 404, 새로 넣는 비활성 품목이면 409.

    keep 은 이미 발주서에 있던 품목 id. 나중에 비활성이 된 품목은 줄을 유지할 수 있다(승인 때 막는다, #34).
    품목은 한 번에 조회한다(품목 수와 무관하게 1번, #84). lock=True 면 품목 번호 순으로 잠근 뒤 최신 값으로 검사한다(추천 초안).
    """
    ids = [i.product_id for i in items]  # 요청의 품목 번호들
    if len(set(ids)) != len(ids):  # 같은 품목이 두 번 들어 있으면
        raise AppError(409, "DUPLICATE_ITEM", "같은 품목을 두 번 넣을 수 없습니다. 수량을 한 줄로 합쳐 주세요.",
                       [{"field": "items", "reason": "duplicate"}])
    stmt = scoped(company_id, Product).where(Product.id.in_(ids)).order_by(Product.id)  # 우리 회사 품목만, 번호 순 (잠금 순서)
    products = {p.id: p for p in db.scalars(stmt.with_for_update() if lock else stmt)}  # 품목 id → 품목 (잠금이면 FOR UPDATE)
    for product_id in ids:  # 요청 순서대로 검사 (첫 번째로 걸린 줄의 오류를 낸다)
        product = products.get(product_id)
        if product is None:  # 없는 id 와 다른 회사 id 는 같은 404 (check_ref 와 같은 모양)
            raise AppError(404, "NOT_FOUND", NOT_FOUND_MESSAGE, [{"field": "items", "reason": "not_found"}])
        if not product.is_active and product_id not in keep:  # 새로 넣는 줄이 비활성이면
            raise inactive("items", f"비활성 품목({product.sku})은 발주에 넣을 수 없습니다.")
    return products


def stock_quantity(box_quantity: int, units_per_box: int | None) -> int:
    if units_per_box is None:
        raise AppError(422, "VALIDATION_ERROR", "박스 입수가 설정된 품목 또는 발주 줄만 박스 수를 보낼 수 있습니다.")
    quantity = box_quantity * units_per_box  # 예: 3박스 × 10개 = 30개
    if quantity > MAX_QUANTITY:
        raise AppError(422, "VALIDATION_ERROR", "박스 수를 환산한 재고 단위 수량은 100만 이하여야 합니다.")
    return quantity


def order_item_values(
    product: Product, quantity: int | None, unit_price: int | None, box_quantity: int | None,
    existing: PurchaseOrderItem | None = None,
) -> dict:
    """수동·추천 발주에 같은 환산을 적용하고 기존 박스 줄은 당시 조건으로 수정한다."""
    if existing is not None and existing.units_per_box is not None:
        units_per_box, box_unit_price = existing.units_per_box, existing.box_unit_price  # 당시 값 유지
        if box_quantity is None:  # 기존 화면의 재고 단위 요청도 기존 박스 줄을 보존한다
            if quantity % units_per_box or unit_price != existing.unit_price:
                raise AppError(422, "VALIDATION_ERROR", "박스 발주 줄은 box_quantity로 박스 수를 변경하세요.")
            box_quantity = quantity // units_per_box
        unit_price = existing.unit_price
    elif box_quantity is not None:
        units_per_box, box_unit_price = product.units_per_box, product.box_unit_cost  # 새 박스 줄의 조건
        unit_price = product.unit_cost  # 기존 단가 응답 칸의 의미 유지
    else:
        return {"quantity": quantity, "unit_price": unit_price}
    return {
        "quantity": stock_quantity(box_quantity, units_per_box),
        "unit_price": unit_price,
        "units_per_box": units_per_box,
        "box_unit_price": box_unit_price,
    }


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
    products = check_items(company_id, db, data.items, keep=set())  # 같은 회사의 품목으로 환산한다
    lines = {i.product_id: order_item_values(products[i.product_id], i.quantity, i.unit_price, i.box_quantity)
             for i in data.items}
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
        delivery_address=data.delivery_address or None,  # 빈 글자는 비움
        payment_terms=data.payment_terms or supplier.payment_terms,  # 안 보내면 공급업체 기본값을 복사 (#157)
    )
    db.add(order)
    db.flush()  # 발주서 id 받기 (확정은 아직)
    db.add_all(PurchaseOrderItem(company_id=company_id, purchase_order_id=order.id, product_id=pid, **values)
               for pid, values in lines.items())
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
        products = check_items(company_id, db, data.items, keep=set(existing))  # 새로 넣는 줄만 활성 필요
        lines = {i.product_id: order_item_values(
            products[i.product_id], i.quantity, i.unit_price, i.box_quantity, existing.get(i.product_id),
        ) for i in data.items}
        gone = [i.id for pid, i in existing.items() if pid not in lines]  # 목록에서 빠진 줄
        if gone:
            db.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.id.in_(gone)))  # 삭제 (DRAFT 줄은 입고 이력이 없다)
        for pid, values in lines.items():
            if pid in existing:  # 있던 줄의 추천 근거는 유지한다
                for field, value in values.items():
                    setattr(existing[pid], field, value)
            else:  # 새 줄
                db.add(PurchaseOrderItem(company_id=company_id, purchase_order_id=order.id, product_id=pid, **values))
    for field, value in data.model_dump(exclude_unset=True, exclude={"items"}).items():  # 납기·메모·납품장소·지불조건 중 보낸 칸 (줄 검사를 모두 통과한 뒤에 바꾼다)
        if field in ("delivery_address", "payment_terms"):
            value = value or None  # 빈 글자는 비움
        setattr(order, field, value)
    db.flush()
    return order


# 허용되는 상태 이동 표 (#34). 동작 → 출발할 수 있는 상태들. 여기 없는 이동은 409 INVALID_STATUS
# RECEIVED 로의 이동은 입고(#35)가 누적 입고량을 보고 정한다
TRANSITIONS = {
    "approve": ({"DRAFT"}, "APPROVED"),  # 승인 (관리자만, 경로에서 검사)
    "order": ({"APPROVED"}, "ORDERED"),  # 공급업체에 발주했음 표시
    "cancel": ({"DRAFT", "APPROVED", "ORDERED"}, "CANCELLED"),  # 취소 (입고 기록이 한 번도 없을 때만)
}


def change_status(company_id: int, db: Session, user_id: int, order_id: int, action: str) -> PurchaseOrder:
    """POST /purchase-orders/{id}/approve·order·cancel. 발주서 행을 잠근 뒤 현재 상태를 읽고 한 단계만 바꾼다.

    잠금 덕분에 같은 발주서에 승인·취소가 동시에 와도 두 번째 요청은 첫 요청의 결과(바뀐 상태)를 보고 409 가 된다.
    입고(#35)도 발주서를 먼저 잠그므로 취소와 입고가 겹치지 않는다(잠금 순서: 회사 → 발주서 → 품목).
    """
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # 발주서 잠금. 다른 회사·없는 id 는 404
    sources, target = TRANSITIONS[action]  # 이 동작이 출발할 수 있는 상태, 도착 상태
    if order.status not in sources:  # 예) DRAFT 에서 바로 order, RECEIVED·CANCELLED 에서 cancel
        raise AppError(409, "INVALID_STATUS", f"{order.status} 상태의 발주서는 이 작업을 할 수 없습니다.", {"status": order.status})
    if action == "approve":
        check_active_for_approval(company_id, db, order)  # 비활성 업체·품목이 들어 있으면 409
        order.approved_by, order.approved_at = user_id, func.now()  # 승인자·승인 시각 (상태 이력 표 대신 칸에 남긴다)
    elif action == "order":
        order.ordered_at = func.now()  # 발주함 표시 시각
    else:
        if orders_with_receipts(company_id, db, [order.id]):  # 전량 정정한 입고도 취소를 막는다.
            raise AppError(409, "CANNOT_CANCEL_RECEIVED", "입고 기록이 있는 발주서는 취소할 수 없습니다.")
        order.cancelled_at = func.now()  # 취소 시각
    order.status = target  # 한 단계만 바꾼다
    db.flush()  # DB 에 보낸다 (확정은 API 가 요청 끝에)
    db.refresh(order)  # func.now() 로 넣은 시각을 실제 값으로 다시 읽는다
    return order


def check_active_for_approval(company_id: int, db: Session, order: PurchaseOrder) -> None:
    """승인 전 검사: 공급업체나 줄의 품목 중 비활성이 있으면 409 INACTIVE_REFERENCE (DRAFT 동안 비활성이 된 경우)."""
    if not db.get(Supplier, order.supplier_id).is_active:  # 발주서와 같은 회사 업체 (작성 때 검사)
        raise inactive("supplier_id", "비활성 공급업체의 발주서는 승인할 수 없습니다. 공급업체를 다시 활성으로 바꾸거나 발주서를 취소하세요.")
    skus = list(db.scalars(select(Product.sku).join(PurchaseOrderItem, PurchaseOrderItem.product_id == Product.id).where(
        PurchaseOrderItem.purchase_order_id == order.id, Product.is_active.is_(False)).order_by(Product.sku)))  # 비활성 품목 SKU 들
    if skus:
        raise inactive("items", f"비활성 품목({', '.join(skus)})이 들어 있어 승인할 수 없습니다. 그 줄을 빼고 다시 승인하세요.")


def get_order(company_id: int, db: Session, order_id: int) -> PurchaseOrder:
    return get_owned(company_id, db, PurchaseOrder, order_id)  # 다른 회사·없는 id 는 404


def receipt_due_condition(receipt_due: ReceiptDue, today: date):
    """대시보드와 목록에 같은 납기 경계를 적용한다."""
    due = PurchaseOrder.due_date  # 발주서의 약속 납기
    match receipt_due:
        case "OVERDUE":
            return due < today
        case "TODAY":
            return due == today
        case "NEXT_7_DAYS":
            return due.between(today + timedelta(days=1), today + timedelta(days=7))
        case "UNSCHEDULED":
            return due.is_(None)


def orders_with_receipts(company_id: int, db: Session, order_ids: list[int]) -> set[int]:
    """입고 기록이 있는 발주서 ID를 한 번에 조회한다."""
    if not order_ids:
        return set()
    return set(db.scalars(select(PurchaseOrderItem.purchase_order_id).distinct().join(
        InventoryMovement, InventoryMovement.purchase_order_item_id == PurchaseOrderItem.id
    ).where(
        PurchaseOrderItem.company_id == company_id, InventoryMovement.company_id == company_id,
        PurchaseOrderItem.purchase_order_id.in_(order_ids), InventoryMovement.movement_type == "RECEIPT",
    )))


def list_orders(
    company_id: int, db: Session, page: PageParams, supplier_id: int | None,
    status: str | None = None, q: str | None = None, receipt_due: ReceiptDue | None = None,
) -> tuple[list[PurchaseOrder], dict]:
    """GET /purchase-orders: 모든 조건을 적용한 뒤 최신순으로 쪽을 나눈다."""
    stmt = scoped(company_id, PurchaseOrder)  # 회사 조건이 붙은 시작점
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)  # 이 업체 발주만 (남의 업체 id 면 빈 목록)
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)  # 이 상태의 발주만
    if receipt_due is not None:
        stmt = stmt.where(PurchaseOrder.status == "ORDERED", receipt_due_condition(receipt_due, seoul_today()))
    if q and (term := q.strip()):
        stmt = stmt.where(PurchaseOrder.po_number.icontains(term, autoescape=True))  # 쪽을 나누기 전에 검색한다.
    return paginate(db, stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()), page)


def received_quantities(company_id: int, db: Session, item_ids: list[int]) -> dict[int, int]:
    """발주 줄별 누적 입고량 = 연결된 RECEIPT 합계 − 연결된 CORRECTION 합계 (erd.md 조회 3). 한 번의 GROUP BY. 없으면 키 없음."""
    if not item_ids:
        return {}
    signed = case((InventoryMovement.movement_type == "RECEIPT", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # 입고 +, 정정 −
    return {k: int(v) for k, v in db.execute(
        select(InventoryMovement.purchase_order_item_id, func.sum(signed)).where(
            InventoryMovement.company_id == company_id,
            InventoryMovement.purchase_order_item_id.in_(item_ids),  # 발주에 연결된 이력만 (입고와 그 정정)
        ).group_by(InventoryMovement.purchase_order_item_id)
    ).all()}  # 줄 id → 누적 입고량


def receive_order(company_id: int, db: Session, user_id: int, order_id: int, data: ReceiptCreate) -> PurchaseOrder:
    """POST /purchase-orders/{id}/receipts: 여러 줄을 한 번에 입고하고, 모든 줄이 차면 RECEIVED 로 바꾼다.

    ① 발주서 잠금 → ② 모든 줄을 먼저 검사(초과면 아무것도 쓰지 않고 409) → ③ 품목 번호 순으로 register_movement(품목 잠금)
    → ④ 누적 입고량으로 상태 결정. commit 은 API 가 요청 끝에 한 번만 해서, 여러 줄이 모두 저장되거나 모두 취소된다.
    """
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # ① 발주서 잠금(잠금 순서: 회사 → 발주서 → 품목). 다른 회사 404
    if order.status != "ORDERED":  # DRAFT·APPROVED 는 아직 주문 전, RECEIVED·CANCELLED 는 끝
        raise AppError(409, "INVALID_STATUS", f"발주함(ORDERED) 상태의 발주서만 입고할 수 있습니다. 지금은 {order.status}입니다.",
                       {"status": order.status})
    today = seoul_today()  # 서울 기준 오늘
    movement_date = data.movement_date or today  # 비우면 오늘 (#29 와 같은 규칙)
    if movement_date > today:  # 아직 일어나지 않은 입고가 재고에 섞이지 않게
        raise AppError(422, "VALIDATION_ERROR", "입고일은 오늘 이후로 할 수 없습니다.", [{"field": "movement_date", "reason": "invalid"}])
    ids = [line.purchase_order_item_id for line in data.items]  # 요청한 발주 줄 번호들
    if len(set(ids)) != len(ids):  # 같은 줄을 두 번 보내면 수량을 합칠지 애매하므로 받지 않는다
        raise AppError(422, "VALIDATION_ERROR", "같은 발주 품목을 두 번 넣을 수 없습니다. 수량을 한 줄로 합쳐 주세요.",
                       [{"field": "items", "reason": "duplicate"}])
    items = {i.id: i for i in db.scalars(scoped(company_id, PurchaseOrderItem).where(
        PurchaseOrderItem.purchase_order_id == order.id))}  # 이 발주서의 줄들 (줄 id → 줄)
    missing = [i for i in ids if i not in items]  # 이 발주서에 없는 줄 (다른 발주서·다른 회사 줄 포함)
    if missing:
        raise AppError(404, "NOT_FOUND", "이 발주서에 없는 품목 줄입니다.", [{"field": "items", "reason": "not_found", "ids": missing}])
    received = received_quantities(company_id, db, list(items))  # ② 잠근 뒤에 읽어야 먼저 끝난 입고·정정이 반영된다
    quantities = {}  # 발주 줄 id → 재고 단위로 환산한 입고량
    for line in data.items:  # 모든 줄을 쓰기 전에 검사: 하나라도 넘치면 아무것도 쓰지 않는다
        item = items[line.purchase_order_item_id]
        quantity = (stock_quantity(line.box_quantity, item.units_per_box)
                    if line.box_quantity is not None else line.quantity)  # 품목의 현재 입수 대신 발주 당시 입수
        quantities[item.id] = quantity
        done = received.get(item.id, 0)  # 지금까지 누적 입고량
        if done + quantity > item.quantity:  # 예) 100 중 70 입고, 40 요청 → 110 > 100
            remaining = item.quantity - done  # 남은 수량 (예: 30)
            raise AppError(
                409, "OVER_RECEIPT",
                f"발주 수량 {item.quantity}개 중 {done}개가 이미 입고되어 {remaining}개까지만 입고할 수 있습니다.",
                {"purchase_order_item_id": item.id, "ordered": item.quantity, "received": done,
                 "remaining": remaining, "requested": quantity},
            )
    for line in sorted(data.items, key=lambda line: items[line.purchase_order_item_id].product_id):  # ③ 품목 번호 오름차순으로 잠근다 (교착 방지)
        item = items[line.purchase_order_item_id]
        quantity = quantities[item.id]
        register_movement(  # 품목 잠금 + 저장(flush). 비활성 품목이어도 ORDERED 발주의 입고는 허용 (check_ref 는 활성을 보지 않는다)
            company_id, db, user_id, product_id=item.product_id, movement_type="RECEIPT", direction="IN",
            quantity=quantity, movement_date=movement_date, purchase_order_item_id=item.id,
        )
        received[item.id] = received.get(item.id, 0) + quantity  # 누적 갱신
    if all(received.get(i.id, 0) >= i.quantity for i in items.values()):  # ④ 모든 줄이 다 찼으면
        order.status = "RECEIVED"  # 전량 입고 (부분이면 ORDERED 그대로)
        last = db.scalar(select(func.max(InventoryMovement.movement_date)).join(
            PurchaseOrderItem, PurchaseOrderItem.id == InventoryMovement.purchase_order_item_id).where(
            PurchaseOrderItem.purchase_order_id == order.id, InventoryMovement.company_id == company_id,
            InventoryMovement.movement_type == "RECEIPT"))  # 이 발주서의 모든 입고 중 가장 늦은 입고일
        order.received_at = datetime.combine(last, time(), SEOUL)  # 실제 입고일 (서울 자정). 예) 11/12 에 입고일 11/10 으로 등록 → 11/10
    db.flush()
    return order


def build_out(company_id: int, db: Session, orders: list[PurchaseOrder]) -> list[dict]:
    """발주서들을 응답 모양으로. 줄·품목·업체·누적 입고량을 목록 전체에 대해 각각 한 번의 조회로 가져온다(N+1 없음)."""
    ids = [o.id for o in orders]
    has_receipts = orders_with_receipts(company_id, db, ids)  # 취소 검사와 같은 기준을 화면에 전달한다.
    items = list(db.scalars(scoped(company_id, PurchaseOrderItem).where(
        PurchaseOrderItem.purchase_order_id.in_(ids)).order_by(PurchaseOrderItem.id))) if ids else []  # 모든 줄
    products = {p.id: p for p in db.scalars(scoped(company_id, Product).where(
        Product.id.in_({i.product_id for i in items})))} if items else {}  # 품목 id → 품목
    suppliers = {s.id: s for s in db.scalars(scoped(company_id, Supplier).where(
        Supplier.id.in_({o.supplier_id for o in orders})))} if orders else {}  # 업체 id → 업체
    received = received_quantities(company_id, db, [i.id for i in items])  # 줄 id → 누적 입고량
    by_order = defaultdict(list)  # 발주서 id → 줄 응답들
    for i in items:
        p = products[i.product_id]
        box_quantity = i.quantity // i.units_per_box if i.units_per_box is not None else None
        by_order[i.purchase_order_id].append(ItemOut(
            id=i.id, product_id=i.product_id, product_sku=p.sku, product_name=p.name, unit=p.unit, quantity=i.quantity,
            unit_price=i.unit_price, recommended_quantity=i.recommended_quantity,
            units_per_box=i.units_per_box, box_unit_price=i.box_unit_price, box_quantity=box_quantity,
            line_total=i.quantity * i.unit_price if box_quantity is None else box_quantity * i.box_unit_price,
            recommendation_reason=i.recommendation_reason, received_quantity=int(received.get(i.id, 0)),
        ))
    return [
        PurchaseOrderOut(
            **{c: getattr(o, c) for c in PurchaseOrderOut.model_fields if c not in ("supplier_name", "items", "has_receipts")},
            supplier_name=suppliers[o.supplier_id].name, items=by_order[o.id], has_receipts=o.id in has_receipts,
        ).model_dump(mode="json")
        for o in orders
    ]
