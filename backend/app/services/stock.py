"""재고 (R2·R3). 현재고 = 입출고 이력 합계. 이력을 쓰는 곳은 register_movement 하나뿐이다.

발주 입고(#35)·정정(#30)도 이 함수를 다시 써서, 음수 재고 차단과 행 잠금을 한 곳에서만 지킨다.
저장 확정(commit)은 이 파일이 하지 않고 호출한 쪽(API 계층)이 요청 끝에 한 번만 한다.
여러 줄을 한 요청에서 쓰다 중간에 실패하면(예: 발주 입고 품목 3개 중 2번째가 초과) 앞 줄까지 함께 취소되게 하려고.
"""

from datetime import date, timedelta  # 날짜와 기간 경계

from sqlalchemy import case, func, select  # 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session, aliased  # DB 세션과 정정의 원본 이력 별칭

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 공통 오류
from app.models import (  # 입출고 이력, 품목, 발주서·발주 품목
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
)
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.movements import CorrectionCreate, MovementCreate  # 등록·정정 요청 모양
from app.schemas.stock import StockTrendDay, StockTrendOut  # 일별 마감 재고 응답
from app.services.tenant import check_ref, get_owned, scoped  # 회사 분리 도우미 (#23)

OUT_TYPES = {"SALE", "DISPOSAL", "OTHER_OUT"}  # 항상 줄이는 유형


def movement_delta():
    return case((InventoryMovement.direction == "IN", InventoryMovement.quantity), else_=-InventoryMovement.quantity)


def current_stock(company_id: int, db: Session, product_id: int) -> int:
    """현재고 = IN 수량 합계 − OUT 수량 합계 (erd.md 조회 1). 이력이 없으면 0."""
    return db.scalar(
        select(func.coalesce(func.sum(movement_delta()), 0)).where(  # 합계, 없으면 0
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.product_id == product_id,  # 이 품목만
        )
    )


def get_stock_trend(company_id: int, db: Session, product_id: int, today: date) -> StockTrendOut:
    """기간 전 잔액과 일별 변동을 읽어 오늘 포함 30일의 마감 재고를 계산한다."""
    product = get_owned(company_id, db, Product, product_id)  # 다른 회사 품목은 404
    start = today - timedelta(days=29)
    movement = InventoryMovement
    original = aliased(InventoryMovement)
    day_bucket = case((movement.movement_date >= start, movement.movement_date))  # 기간 전 이력은 한 그룹으로 모은다
    net_receipts = case(
        (movement.movement_type == "RECEIPT", movement.quantity),
        (original.movement_type == "RECEIPT", -movement.quantity),
        else_=0,
    )
    totals = {
        day: (delta, receipts) for day, delta, receipts in db.execute(
            select(day_bucket, func.sum(movement_delta()), func.sum(net_receipts))
            .select_from(movement)
            .outerjoin(original, (original.id == movement.reverses_movement_id)
                       & (original.company_id == company_id) & (original.product_id == product_id)
                       & (movement.movement_date >= start))  # 기간 전에는 입고량을 따로 셀 필요가 없다
            .where(movement.company_id == company_id, movement.product_id == product_id, movement.movement_date <= today)
            .group_by(day_bucket)
        )
    }
    closing = totals.get(None, (None, 0))[0]  # 이력이 없던 기간은 실제 재고 0과 구분한다
    days = []
    for offset in range(30):
        day = start + timedelta(days=offset)
        previous = closing
        receipts = 0
        if day in totals:
            delta, receipts = totals[day]
            closing = (closing or 0) + delta  # 날짜 순서로 수량을 반영한다
        days.append(StockTrendDay(
            day=day, closing_stock=closing, received_quantity=receipts,
            reached_zero=previous is not None and previous > 0 and closing == 0,
        ))
    return StockTrendOut(product_id=product.id, name=product.name, sku=product.sku, unit=product.unit, days=days)


def validate_new_movement(data: MovementCreate, today: date) -> str:
    """POST /inventory-movements 입력 규칙 검사. 통과하면 저장할 방향(IN/OUT)을 돌려준다. 어기면 422."""

    def invalid(field: str, message: str):
        return AppError(422, "VALIDATION_ERROR", message, [{"field": field, "reason": "invalid"}])  # 어느 칸인지 함께

    if data.movement_type == "SALE" and data.sales_channel is None:
        raise invalid("sales_channel", "판매 출고에는 판매 채널이 필요합니다.")  # R7
    if data.movement_type != "SALE" and data.sales_channel is not None:
        raise invalid("sales_channel", "판매 채널은 판매 출고에만 넣을 수 있습니다.")  # chk_movement 와 같은 규칙
    if data.movement_type == "ADJUSTMENT":
        if data.direction is None:
            raise invalid("direction", "재고 조정에는 방향(IN 늘림 / OUT 줄임)이 필요합니다.")
        if data.reason is None:
            raise invalid("reason", "재고 조정에는 사유가 필요합니다.")  # R10
    elif data.direction is not None:
        raise invalid("direction", "방향은 재고 조정에만 넣습니다. 다른 유형은 서버가 정합니다.")  # 잘못된 조합을 조용히 무시하지 않는다
    if data.movement_date is not None and data.movement_date > today:
        raise invalid("movement_date", "입출고일은 오늘 이후로 할 수 없습니다.")  # 아직 일어나지 않은 입출고가 재고·추천에 섞이지 않게

    if data.movement_type == "ADJUSTMENT":
        return data.direction  # 조정은 요청한 방향
    return "OUT" if data.movement_type in OUT_TYPES else "IN"  # 출고 3종은 OUT, 입고는 IN


def register_movement(
    company_id: int,
    db: Session,
    user_id: int,
    *,
    product_id: int,
    movement_type: str,
    direction: str,
    quantity: int,
    movement_date: date,
    sales_channel: str | None = None,
    reason: str | None = None,
    memo: str | None = None,
    purchase_order_item_id: int | None = None,
    reverses_movement_id: int | None = None,
) -> tuple[InventoryMovement, int]:
    """이력 한 줄을 쓰는 유일한 함수. 한 트랜잭션 안에서 ① 품목 줄 잠금 ② 현재고 계산 ③ 0 미만이면 거절 ④ 저장(flush).

    commit 은 하지 않는다. 호출한 쪽이 commit 해야 확정되고, 그때 잠금이 풀린다.

    돌려주는 값: (저장한 이력, 저장 직후 재고)
    """
    check_ref(company_id, db, Product, product_id, "product_id", lock=True)  # ① 같은 회사 품목이 아니면 404. 잠금: 같은 품목의 다른 등록은 여기서 기다린다
    stock = current_stock(company_id, db, product_id)  # ② 잠근 뒤에 읽어야 먼저 끝난 등록이 반영된 값을 본다
    after = stock + quantity if direction == "IN" else stock - quantity  # 저장 직후 재고 (예: 52 − 30 = 22)
    if after < 0:  # ③ 음수가 되면 (R3)
        verb = "출고할" if movement_type in OUT_TYPES else "줄일"  # 출고 3종은 "출고", 감소 조정·정정은 "줄이기"
        raise AppError(
            409, "INSUFFICIENT_STOCK", f"현재고 {stock}개보다 많이 {verb} 수 없습니다.",
            {"current_stock": stock, "requested": quantity},
        )  # 저장 없이 끝난다. 잠금은 요청이 끝나 세션이 닫힐 때 풀린다
    movement = InventoryMovement(
        company_id=company_id, product_id=product_id, created_by=user_id,  # 회사·품목·등록자
        movement_type=movement_type, direction=direction, quantity=quantity, movement_date=movement_date,
        sales_channel=sales_channel, reason=reason, memo=memo,
        purchase_order_item_id=purchase_order_item_id, reverses_movement_id=reverses_movement_id,
    )
    db.add(movement)  # ④ 저장
    db.flush()  # DB 에 보내 id 를 받는다 (확정은 아직). 호출한 쪽의 commit 때 확정되고 잠금이 풀린다
    return movement, after


def create_movement(company_id: int, db: Session, user_id: int, data: MovementCreate) -> tuple[InventoryMovement, int]:
    """POST /inventory-movements: 직접 입고·출고 3종·조정. 비활성 품목도 허용한다(남은 재고 처리, 반품 입고)."""
    today = seoul_today()  # 서울 기준 오늘
    direction = validate_new_movement(data, today)  # 입력 규칙 검사 + 방향 결정
    return register_movement(
        company_id, db, user_id,
        product_id=data.product_id, movement_type=data.movement_type, direction=direction,
        quantity=data.quantity, movement_date=data.movement_date or today,  # 날짜를 비우면 오늘
        sales_channel=data.sales_channel, reason=data.reason, memo=data.memo,
    )


def corrected_quantity(company_id: int, db: Session, original_id: int) -> int:
    """한 이력에 대해 이미 등록된 정정 수량 합계 (없으면 0)."""
    return db.scalar(
        select(func.coalesce(func.sum(InventoryMovement.quantity), 0)).where(
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.reverses_movement_id == original_id,  # 이 원래 이력을 가리키는 정정만
        )
    )


def create_correction(
    company_id: int, db: Session, user_id: int, original_id: int, data: CorrectionCreate
) -> tuple[InventoryMovement, int]:
    """POST /inventory-movements/{id}/corrections: 원래 이력을 가리키는 CORRECTION 한 줄을 쌓는다 (원래 이력은 그대로).

    잠금 순서는 발주서 → 품목. 발주 입고(#35)도 같은 순서로 잠가야 서로 기다리다 멈추는 일(교착)이 없다.
    """
    original = get_owned(company_id, db, InventoryMovement, original_id)  # 없거나 다른 회사 이력이면 404
    if original.movement_type == "CORRECTION":  # 정정의 정정은 받지 않는다 (임시 확정)
        raise AppError(422, "VALIDATION_ERROR", "정정 이력은 다시 정정할 수 없습니다. 원래 이력을 정정하세요.",
                       [{"field": "id", "reason": "is_correction"}])

    if original.purchase_order_item_id is not None:  # 원래 이력이 발주 입고면
        item = db.get(PurchaseOrderItem, original.purchase_order_item_id)  # 연결된 발주 품목 (같은 회사 이력이 가리키므로 같은 회사)
        order = get_owned(company_id, db, PurchaseOrder, item.purchase_order_id, lock=True)  # ① 발주서 잠금: 정정 중에 상태가 바뀌지 않게
        if order.status != "ORDERED":  # RECEIVED·CANCELLED 등이면
            raise AppError(409, "INVALID_STATUS", "발주가 ORDERED 상태일 때만 입고를 정정할 수 있습니다.",
                           {"status": order.status})  # RECEIVED 가 된 발주의 입고는 정정 불가 (erd.md 한계)

    check_ref(company_id, db, Product, original.product_id, "product_id", lock=True)  # ② 품목 잠금: 같은 원래 이력의 동시 정정은 여기서 줄을 선다
    already = corrected_quantity(company_id, db, original.id)  # ③ 잠근 뒤에 읽어야 먼저 끝난 정정이 반영된다
    if already + data.quantity > original.quantity:  # 정정 합계가 원래 수량을 넘으면
        raise AppError(
            409, "CORRECTION_EXCEEDS",
            f"정정 수량 합계가 원래 수량({original.quantity}개)을 넘을 수 없습니다. 이미 {already}개를 정정했습니다.",
            {"original_quantity": original.quantity, "already_corrected": already, "requested": data.quantity},
        )

    return register_movement(  # ④ 음수 재고 검사와 저장은 출고와 같은 한 곳에서 (품목 잠금은 이미 잡고 있다)
        company_id, db, user_id,
        product_id=original.product_id,  # 품목은 원래와 같다
        movement_type="CORRECTION",
        direction="OUT" if original.direction == "IN" else "IN",  # 방향은 원래의 반대 (입고 정정 → 재고 감소)
        quantity=data.quantity,
        movement_date=original.movement_date,  # 원래 이력의 날짜를 따른다: 날짜로 묶는 집계(이번 달 출고 등)가 바로 맞게. 고친 시각은 created_at
        reason=data.reason,
        purchase_order_item_id=original.purchase_order_item_id,  # 발주 입고 정정이면 같은 발주 품목 (누적 입고량 = 입고 − 정정)
        reverses_movement_id=original.id,  # 원래 이력을 가리킨다
    )


def stock_rows(company_id: int, db: Session, products: list[Product]) -> list[dict]:
    """품목들의 현재고를 한 번의 GROUP BY 로 구해 응답 칸으로 만든다 (품목마다 따로 묻지 않는다). 이력 없는 품목은 0."""
    signed = case((InventoryMovement.direction == "IN", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # IN +, OUT −
    sums = dict(db.execute(
        select(InventoryMovement.product_id, func.sum(signed))  # 품목별 합계
        .where(InventoryMovement.company_id == company_id, InventoryMovement.product_id.in_([p.id for p in products]))  # 우리 회사, 이 쪽 품목들만
        .group_by(InventoryMovement.product_id)
    ).all())  # 품목 id → 현재고
    return [
        {"product_id": p.id, "sku": p.sku, "name": p.name, "unit": p.unit, "safety_stock": p.safety_stock,
         "is_active": p.is_active, "current_stock": int(sums.get(p.id, 0))}  # 이력이 없으면 0
        for p in products
    ]


def list_movements(
    company_id: int, db: Session, page: PageParams,
    product_id: int | None, movement_types: list[str] | None, date_from: date | None, date_to: date | None,
    sort: str = "date",
) -> tuple[list[InventoryMovement], dict]:
    """GET /inventory-movements: 우리 회사 이력. 기간은 양 끝 날짜 포함.

    movement_types: 이 유형들 중 하나인 이력 (None 이면 전체. 값이 하나면 예전의 "이 유형만"과 같다).
    sort="date"(기본): 입출고일 최신순, 같은 날은 나중에 등록한 것 먼저.
    sort="registered": 등록 순서 최신순(created_at, 같은 시각이면 번호가 큰 것 먼저) - 과거 날짜로 방금 등록한 줄도 맨 위에 온다.
    """
    stmt = scoped(company_id, InventoryMovement)  # 회사 조건이 붙은 시작점
    if product_id is not None:
        stmt = stmt.where(InventoryMovement.product_id == product_id)  # 이 품목만
    if movement_types:
        stmt = stmt.where(InventoryMovement.movement_type.in_(movement_types))  # 이 유형들 중 하나 (예: SALE, DISPOSAL)
    if date_from is not None:
        stmt = stmt.where(InventoryMovement.movement_date >= date_from)  # 이 날짜부터
    if date_to is not None:
        stmt = stmt.where(InventoryMovement.movement_date <= date_to)  # 이 날짜까지
    if sort == "registered":
        order = (InventoryMovement.created_at.desc(), InventoryMovement.id.desc())  # 등록 순서 최신순
    else:
        order = (InventoryMovement.movement_date.desc(), InventoryMovement.id.desc())  # 입출고일 최신순 (기본)
    return paginate(db, stmt.order_by(*order), page)
