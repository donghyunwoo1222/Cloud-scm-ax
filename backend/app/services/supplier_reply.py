"""공급업체 확인·납기 회신 (#265 PR2). 로그인 없는 공개 경로가 쓰는 업무 규칙.

- 요청에서 회사·발주 id 를 받지 않는다. 메일 링크 토큰의 해시로 찾은 발주서 행 하나와 그 행의 company_id 로만 조회한다.
- 보기(view)는 아무것도 바꾸지 않는다(메일 보안 검사기가 링크를 미리 열어도 기록이 생기지 않게, 확인은 사람이 누르는 POST).
- 응답은 PUBLIC_KEYS·ITEM_KEYS 허용 칸만 내보낸다(test_supplier_reply.py 가 고정). 단가·금액·내부 id·연락처는 없다.
- 상태는 바꾸지 않는다: 확인 시각·회신 납기·회신 횟수 칸과 변경 이력(changed_by NULL = 공급업체)만 남긴다.
"""

from datetime import UTC, date, datetime  # 회신 납기, 확인 시각

from sqlalchemy import func, select  # DB 현재 시각, SELECT
from sqlalchemy.orm import Session  # DB 세션

from app.auth.security import hash_reset_token  # 토큰 → SHA-256 (발급 때와 같은 함수)
from app.clock import SEOUL, seoul_today  # 서울 기준 날짜
from app.config import settings  # SUPPLIER_LINK_ENABLED 스위치
from app.errors import AppError  # 공통 오류
from app.models import Company, PurchaseOrder  # 표들
from app.services import purchase_orders as po_service  # 줄 응답(build_out) 재사용
from app.services.po_change_log import log_change, text_of  # 변경 이력 (#181)

REPLY_LIMIT = 5  # 회신 납기를 바꿀 수 있는 횟수 (같은 날짜 재전송·확인만은 세지 않는다)
INVALID_MESSAGE = "링크가 만료되었거나 더 이상 쓸 수 없습니다"  # 없음·만료·옛 토큰·스위치 꺼짐을 구분하지 않는다
NOTICES = {  # 상태 안내 문장 (공개 화면이 그대로 보여 준다)
    "CANCELLED": "취소된 발주입니다",
    "RECEIVED": "입고 완료된 발주입니다",
    "RECEIVED_CLOSED": "입고 완료(남은 수량은 받지 않기로 함)",  # 잔량 마감(#252): 메일 없이 이 화면에서만 알린다
}
PUBLIC_KEYS = ("state", "notice", "can_reply", "replies_left", "po_number", "buyer_name", "order_date",
               "due_date", "supplier_due_date", "supplier_confirmed_at", "items")  # 공개 응답 허용 칸 (문서: supplier-document-fields.md 5절)
ITEM_KEYS = ("name", "options", "quantity", "unit")  # 품목 한 줄의 허용 칸


def invalid() -> AppError:
    return AppError(404, "SUPPLIER_LINK_INVALID", INVALID_MESSAGE)


def find_order(db: Session, token: str, lock: bool = False) -> PurchaseOrder:
    """토큰 해시로 만료 전 발주서를 찾는다. 스위치 꺼짐·없음·만료·옛 토큰·토큰이 생길 수 없는 상태는 모두 같은 404."""
    if not settings.supplier_link_enabled:
        raise invalid()
    stmt = select(PurchaseOrder).where(PurchaseOrder.supplier_token_hash == hash_reset_token(token),  # 원본은 SQL 에도 넣지 않는다
                                       PurchaseOrder.supplier_token_expires_at > func.now())
    order = db.scalar(stmt.with_for_update() if lock else stmt)  # 확인은 발주서 행을 잠근다 (취소·입고와 같은 잠금)
    if order is None or order.status not in ("ORDERED", "RECEIVED", "CANCELLED"):  # 토큰은 발송(→ORDERED) 때만 생긴다
        raise invalid()
    return order


def public_view(db: Session, order: PurchaseOrder) -> dict:
    """공개 응답. 어떤 상태든 키 목록은 PUBLIC_KEYS 그대로이고, 해당 없는 칸은 null·빈 목록이다."""
    if order.status == "CANCELLED":  # 취소: 안내 문장만 (품목·납기도 보여 주지 않는다)
        return {**dict.fromkeys(PUBLIC_KEYS), "state": "CANCELLED", "notice": NOTICES["CANCELLED"],
                "can_reply": False, "items": []}
    out = po_service.build_out(order.company_id, db, [order])[0]  # 이 발주서의 회사로만 조회 (줄·박스·마감 계산 재사용)
    if order.status == "ORDERED":
        state = "REPLYABLE"  # 부분 입고여도 회신 가능
    else:
        state = "RECEIVED_CLOSED" if any(i["closed_quantity"] for i in out["items"]) else "RECEIVED"
    items = []
    for i in out["items"]:  # 단가·금액·SKU·내부 id·추천 사유는 고르지 않는다
        boxed = i["box_quantity"] is not None  # 박스 발주는 문서·메일처럼 박스 단위로
        items.append({
            "name": i["product_name"],
            "options": " / ".join(v for v in (i["color"], i["size"], i["spec"]) if v) or None,  # 예) 빨강 / L
            "quantity": i["box_quantity"] if boxed else i["quantity"],
            "unit": i["order_unit"] if boxed else i["unit"],
        })
    return {
        "state": state,
        "notice": NOTICES.get(state),
        "can_reply": state == "REPLYABLE",  # 확인만 보내기는 횟수를 다 써도 된다
        "replies_left": max(0, REPLY_LIMIT - order.supplier_reply_count),  # 날짜를 바꿀 수 있는 남은 횟수
        "po_number": order.po_number,
        "buyer_name": db.get_one(Company, order.company_id).name,  # 지금 회사 이름 (메일 제목과 같은 값)
        "order_date": order.created_at.astimezone(SEOUL).date().isoformat(),  # 발주일 = 작성일 (문서와 같은 계산)
        "due_date": text_of(order.due_date),  # 약속 납기
        "supplier_due_date": text_of(order.supplier_due_date),  # 회신 납기
        "supplier_confirmed_at": text_of(order.supplier_confirmed_at),
        "items": items,
    }


def view(db: Session, token: str) -> dict:
    """POST /supplier-reply/view: 읽기만 한다."""
    return public_view(db, find_order(db, token))


def one_year_later(today: date) -> date:
    """회신 납기의 늦은 끝. 예) 2026-11-18 → 2027-11-18, 2028-02-29 → 2029-02-28."""
    try:
        return today.replace(year=today.year + 1)
    except ValueError:  # 2/29 → 다음 해에 없으면 2/28
        return today.replace(year=today.year + 1, day=28)


def confirm(db: Session, token: str, due_date: date | None) -> dict:
    """POST /supplier-reply/confirm. 발주서 잠금 → 상태 확인 → 확인 시각·회신 납기 기록(커밋은 API).

    판단 순서: 같은 날짜 재전송은 변화 없이 성공 → 확인만은 횟수와 무관하게 성공 → 날짜가 실제로 바뀔 때만 5번 제한.
    """
    today = seoul_today()
    if due_date is not None and not (today <= due_date <= one_year_later(today)):  # 어제 이전·1년 초과
        raise AppError(422, "VALIDATION_ERROR", "납기일은 오늘부터 1년 안의 날짜로 입력해 주세요.",
                       [{"field": "due_date", "reason": "out_of_range"}])
    order = find_order(db, token, lock=True)  # 잠근 뒤 상태를 다시 본다 (취소와 겹치면 먼저 끝난 쪽 결과를 본다)
    if order.status != "ORDERED":  # 취소·입고 완료는 보기만
        raise AppError(409, "SUPPLIER_REPLY_CLOSED", f"{NOTICES['CANCELLED' if order.status == 'CANCELLED' else 'RECEIVED']}. 확인·회신은 할 수 없습니다.")
    changes = []
    if order.supplier_confirmed_at is None:  # 처음 확인만 기록 (다시 눌러도 첫 확인 시각 유지)
        now = datetime.now(UTC)
        changes.append(("supplier_confirmed_at", None, text_of(now)))
        order.supplier_confirmed_at = now
    if due_date is not None and due_date != order.supplier_due_date:  # 같은 날짜면 아무것도 안 바꾼다 (제한보다 먼저 본다)
        if order.supplier_reply_count >= REPLY_LIMIT:
            raise AppError(409, "SUPPLIER_REPLY_LIMIT",
                           f"납기 회신은 {REPLY_LIMIT}번까지만 할 수 있습니다. 납기가 또 바뀌면 발주 메일에 답장해 주세요.")
        changes.append(("supplier_due_date", text_of(order.supplier_due_date), text_of(due_date)))  # 이전 → 이후
        order.supplier_due_date = due_date
        order.supplier_reply_count += 1
    log_change(db, order.company_id, order.id, None, changes)  # 행위자 NULL = 공급업체(메일 링크)
    db.flush()
    return public_view(db, order)  # view 와 같은 모양: 공개 화면이 결과를 바로 그린다
