"""재고 (R2·R3). 현재고 = 입출고 이력 합계. 이력을 쓰는 곳은 register_movement(한 줄)·register_movements(여러 줄, #211) 뿐이다.

발주 입고(#35)·정정(#30)도 이 함수를 다시 써서, 음수 재고 차단과 행 잠금을 한 곳에서만 지킨다.
저장 확정(commit)은 이 파일이 하지 않고 호출한 쪽(API 계층)이 요청 끝에 한 번만 한다.
여러 줄을 한 요청에서 쓰다 중간에 실패하면(예: 발주 입고 품목 3개 중 2번째가 초과) 앞 줄까지 함께 취소되게 하려고.
"""

from datetime import date, timedelta  # 날짜와 기간 경계

from sqlalchemy import case, func, insert, select  # 조건 합계, 합계, 여러 줄 INSERT, SELECT 문
from sqlalchemy.orm import Session, aliased  # DB 세션과 정정의 원본 이력 별칭

from app.clock import (  # 입출고일 공통 검사(미래·5년 하한), 서울 기준 오늘
    date_problem,
    oldest_allowed,
    seoul_today,
)
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
from app.services.recommend import SALES_WINDOW_DAYS  # 최근 30일 (추천 순수 함수와 같은 기간)
from app.services.tenant import (  # 회사 분리 도우미 (#23)
    NOT_FOUND_MESSAGE,
    check_ref,
    get_owned,
    scoped,
)

OUT_TYPES = {"SALE", "DISPOSAL", "OTHER_OUT"}  # 항상 줄이는 유형
LARGE_QUANTITY_MULTIPLE = 3  # 큰 수량 경고: 최근 30일 판매의 3배 초과 (#190 임시값, 사용자 테스트 후 재검토)


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


def net_sales(company_id: int, db: Session, today: date, product_ids: list[int] | None = None) -> dict[int, int]:
    """품목별 최근 30일 순판매 = 기간 안 SALE − 그 SALE 을 가리키는 정정 합계 (erd.md 조회 2). 한 번의 쿼리. 판매가 없으면 키 없음.

    기간은 오늘 포함 30일(오늘−29일 ~ 오늘)이고 원래 SALE 의 날짜로 판단한다. 폐기·조정의 정정은 SALE 에 붙지 않아 빼지 않는다.
    예) 오늘 11-04: 10-06 판매는 포함(오늘−29일), 10-05 판매는 제외(오늘−30일). SALE 100 + 정정 90 → 10 (S13).
    product_ids 를 주면 그 품목만 본다(큰 수량 경고, #190). 정정은 원래 이력과 품목이 같아 같은 조건으로 줄인다.
    """
    only = [InventoryMovement.product_id.in_(product_ids)] if product_ids is not None else []  # 품목 조건 (없으면 회사 전체)
    corrected = (
        select(InventoryMovement.reverses_movement_id.label("original_id"), func.sum(InventoryMovement.quantity).label("qty"))  # 원래 이력별 정정 합계
        .where(InventoryMovement.company_id == company_id, InventoryMovement.movement_type == "CORRECTION", *only)
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
            *only,
        ).group_by(InventoryMovement.product_id)
    ).all()}


def check_movement_date(day: date, today: date, label: str) -> None:
    """직접 입출고·발주 입고의 날짜 검사 (가져오기와 같은 date_problem). 미래이거나 5년보다 이르면 422."""
    problem = date_problem(day, today)
    if problem == "FUTURE_DATE":
        message = f"{label}은 오늘 이후로 할 수 없습니다."
    elif problem == "TOO_OLD_DATE":
        message = f"{label}은 {oldest_allowed(today)}보다 이를 수 없습니다. 연도를 확인해 주세요."  # 예) 0202-11-01 오타
    else:
        return
    raise AppError(422, "VALIDATION_ERROR", message, [{"field": "movement_date", "reason": "invalid"}])


def movement_warnings(
    company_id: int, db: Session, lines: list[tuple[Product, int]], today: date, *, check_inactive: bool
) -> list[dict]:
    """저장 전에 사용자 확인이 필요한 입력 (#190). 막지 않고 목록만 만든다. lines = [(품목, 재고 단위 수량)].

    LARGE_QUANTITY: 수량 > 최근 30일 순판매 × 3 (예: 한 달 판매 300 → 900 까지는 통과, 901 부터 경고). 30일 판매 0 이면 검사하지 않는다.
    INACTIVE_PRODUCT: 비활성 품목 (직접 입출고만. ORDERED 발주 입고는 check_inactive=False).
    """
    sales = net_sales(company_id, db, today, [p.id for p, _ in lines])  # 품목 id → 30일 순판매 (추천과 같은 숫자)
    warnings = []
    for product, quantity in lines:
        sold = sales.get(product.id, 0)
        if sold > 0 and quantity > sold * LARGE_QUANTITY_MULTIPLE:
            warnings.append({"code": "LARGE_QUANTITY", "product_id": product.id, "sku": product.sku, "quantity": quantity,
                             "sales_30d": sold, "limit": sold * LARGE_QUANTITY_MULTIPLE})
        if check_inactive and not product.is_active:
            warnings.append({"code": "INACTIVE_PRODUCT", "product_id": product.id, "sku": product.sku})
    return warnings


def require_confirmed(warnings: list[dict], confirmed: bool) -> None:
    """경고가 있는데 사용자가 아직 확인하지 않았으면 409 CONFIRM_REQUIRED. 아무것도 저장하기 전에 부른다."""
    if not warnings or confirmed:
        return
    sentences = [
        f"{w['sku']}: 수량 {w['quantity']:,}개가 최근 30일 판매({w['sales_30d']:,}개)의 {LARGE_QUANTITY_MULTIPLE}배를 넘습니다."
        if w["code"] == "LARGE_QUANTITY" else f"{w['sku']}: 비활성 품목입니다."
        for w in warnings
    ]
    raise AppError(409, "CONFIRM_REQUIRED", "확인이 필요합니다. " + " ".join(sentences) + " 맞으면 확인 후 다시 보내 주세요.",
                   {"warnings": warnings})


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
    if data.movement_date is not None:
        check_movement_date(data.movement_date, today, "입출고일")  # 미래·5년보다 이른 날짜는 422 (가져오기와 같은 규칙)

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
    external_ref: str | None = None,
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
        external_ref=external_ref,  # 가져오기 파일의 주문번호 (중복 반영을 DB 가 막는다)
    )
    db.add(movement)  # ④ 저장
    db.flush()  # DB 에 보내 id 를 받는다 (확정은 아직). 호출한 쪽의 commit 때 확정되고 잠금이 풀린다
    return movement, after


BULK_TYPES = OUT_TYPES | {"RECEIPT"}  # 한 번에 쓸 수 있는 유형: 방향이 하나로 정해지는 것만 (조정·정정은 각자 규칙이 있어 register_movement 로)


def register_movements(
    company_id: int,
    db: Session,
    user_id: int,
    *,
    movement_type: str,
    rows: list[dict],
    sales_channel: str | None = None,
) -> None:
    """같은 유형의 이력 여러 줄을 한 번에 쓴다 (#211). register_movement 를 줄마다 부른 것과 결과가 같다.

    rows: [{"product_id", "quantity", "movement_date", "external_ref"(선택)}, ...], 이 순서대로 저장한다(id 순서).
    ① 품목들을 번호순으로 잠근다(이미 잡았으면 바로 통과). 이 회사 품목이 아닌 것이 섞이면 404 (check_ref 와 같은 오류)
    ② 모든 줄을 INSERT 한 번으로 저장 ③ 저장 뒤 품목별 재고를 한 번에 다시 읽어 0 미만이면 409 (저장은 요청과 함께 취소)
    ③이 끝에 한 번이어도 되는 이유: 한 호출 안의 줄은 방향이 모두 같아 재고가 한쪽으로만 움직인다.
    예) 재고 10, 판매 6·4 → 4, 0. 마지막이 0 이상이면 중간도 모두 0 이상이라 줄마다 검사한 것과 판정이 같다.
    commit 은 하지 않는다 (register_movement 와 같다).
    """
    if movement_type not in BULK_TYPES:
        raise AppError(422, "VALIDATION_ERROR", "한 번에 쓸 수 없는 이력 유형입니다.", [{"field": "movement_type", "reason": "invalid"}])
    if any(type(r["quantity"]) is not int or r["quantity"] < 1 for r in rows):  # bool·실수도 막는다
        raise AppError(422, "VALIDATION_ERROR", "수량은 1 이상의 정수여야 합니다.", [{"field": "quantity", "reason": "invalid"}])
    if not rows:
        return
    direction = "OUT" if movement_type in OUT_TYPES else "IN"
    product_ids = {r["product_id"] for r in rows}
    locked = db.execute(  # ① 회사 조건을 건 채 번호순 잠금: 다른 회사 품목은 결과에 나오지 않는다
        select(Product.id).where(Product.company_id == company_id, Product.id.in_(product_ids))
        .order_by(Product.id).with_for_update()
    ).all()
    if len(locked) != len(product_ids):
        raise AppError(404, "NOT_FOUND", NOT_FOUND_MESSAGE, [{"field": "product_id", "reason": "not_found"}])
    db.execute(insert(InventoryMovement), [  # ② 추가만 한다 (이력은 고치거나 지우지 않는다)
        {"company_id": company_id, "product_id": r["product_id"], "created_by": user_id, "movement_type": movement_type,
         "direction": direction, "quantity": r["quantity"], "movement_date": r["movement_date"],
         "sales_channel": sales_channel, "external_ref": r.get("external_ref")}
        for r in rows
    ])
    after = dict(db.execute(  # ③ 저장 뒤 재고 (품목 잠금 아래라 다른 요청은 끼어들지 못한다)
        select(InventoryMovement.product_id, func.sum(movement_delta()))
        .where(InventoryMovement.company_id == company_id, InventoryMovement.product_id.in_(product_ids))
        .group_by(InventoryMovement.product_id)
    ).all())
    short = sorted(pid for pid in product_ids if after.get(pid, 0) < 0)
    if short:
        pid = short[0]
        requested = sum(r["quantity"] for r in rows if r["product_id"] == pid)
        stock = after[pid] + requested  # 저장 전 재고 (OUT 만 음수가 될 수 있다)
        raise AppError(409, "INSUFFICIENT_STOCK", f"현재고 {stock}개보다 많이 출고할 수 없습니다.",
                       {"current_stock": stock, "requested": requested, "product_id": pid})


def create_movement(company_id: int, db: Session, user_id: int, data: MovementCreate) -> tuple[InventoryMovement, int]:
    """POST /inventory-movements: 직접 입고·출고 3종·조정. 비활성 품목도 허용한다(남은 재고 처리, 반품 입고)."""
    today = seoul_today()  # 서울 기준 오늘
    direction = validate_new_movement(data, today)  # 입력 규칙 검사 + 방향 결정
    product = check_ref(company_id, db, Product, data.product_id, "product_id")  # 다른 회사·없는 품목은 404 (잠금은 register_movement 에서)
    require_confirmed(movement_warnings(company_id, db, [(product, data.quantity)], today, check_inactive=True),
                      data.confirm_warnings)  # 큰 수량·비활성 품목은 확인 전이면 409, 아무것도 저장하지 않는다
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
        {"product_id": p.id, "sku": p.sku, "name": p.name, "unit": p.unit, "color": p.color, "size": p.size, "spec": p.spec, "group_code": p.group_code, "safety_stock": p.safety_stock,
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
