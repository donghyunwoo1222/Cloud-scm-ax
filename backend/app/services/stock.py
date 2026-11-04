"""재고 (R2·R3). 현재고 = 입출고 이력 합계. 이력을 쓰는 곳은 register_movement 하나뿐이다.

발주 입고(#35)·정정(#30)도 이 함수를 다시 써서, 음수 재고 차단과 행 잠금을 한 곳에서만 지킨다.
저장 확정(commit)은 이 파일이 하지 않고 호출한 쪽(API 계층)이 요청 끝에 한 번만 한다.
여러 줄을 한 요청에서 쓰다 중간에 실패하면(예: 발주 입고 품목 3개 중 2번째가 초과) 앞 줄까지 함께 취소되게 하려고.
"""

from datetime import date  # 날짜

from sqlalchemy import case, func, select  # 조건 합계, 합계, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 공통 오류
from app.models import InventoryMovement, Product  # 입출고 이력, 품목 표
from app.schemas.movements import MovementCreate  # 등록 요청 모양
from app.services.tenant import check_ref  # 회사 분리 도우미 (#23)

OUT_TYPES = {"SALE", "DISPOSAL", "OTHER_OUT"}  # 항상 줄이는 유형


def current_stock(company_id: int, db: Session, product_id: int) -> int:
    """현재고 = IN 수량 합계 − OUT 수량 합계 (erd.md 조회 1). 이력이 없으면 0."""
    signed = case((InventoryMovement.direction == "IN", InventoryMovement.quantity), else_=-InventoryMovement.quantity)  # IN 은 +, OUT 은 −
    return db.scalar(
        select(func.coalesce(func.sum(signed), 0)).where(  # 합계, 없으면 0
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.product_id == product_id,  # 이 품목만
        )
    )


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
