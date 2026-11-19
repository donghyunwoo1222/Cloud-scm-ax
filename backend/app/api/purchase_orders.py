"""발주서 경로: 작성·수정·조회(#33), 상태 변경 approve·order·cancel(#34), 입고(#35), 잔량 마감(#252), 공급업체 회신 기록(#265). 승인만 관리자, 나머지는 둘 다."""

import logging  # 서버 로그 (메일 이력 저장 실패 알림)
from typing import Annotated, Literal  # 타입에 부가 정보를 붙이는 도구, 정해진 값 중 하나

from fastapi import (  # 라우터, 쿼리 문자열 칸, 요청 경로(멱등 키), 파일 응답
    APIRouter,
    Query,
    Request,
    Response,
)

from app.auth.deps import AdminUser, CurrentUser  # 관리자만 / 로그인 사용자 (#22·#23)
from app.db import DB, ReadDB  # 요청마다 DB 세션, 한 시점으로 읽는 조회 세션
from app.errors import AppError  # 공통 오류
from app.models import PoEmailLog  # 메일 발송 이력 (#182, 저장 실패 때 UNSAVED 행)
from app.pagination import Page  # page·page_size
from app.schemas.common import (  # 멱등 키 헤더, 번호 칸 (DB 범위를 넘으면 422, #71)
    IdempotencyKeyHeader,
    PathId,
    QueryId,
)
from app.schemas.purchase_orders import (  # 요청 모양
    ChangeLogOut,
    EmailLogOut,
    OrderCancel,
    OrderCloseRemaining,
    OrderEmailSend,
    PoStatus,
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
    ReceiptCreate,
    ReceiptDue,
    SupplierReplyRecord,
)
from app.services import (
    export,  # 목록 내보내기 (#191)
    idempotency,  # 같은 요청 키는 한 번만 처리 (#190)
    po_change_log,  # 발주서 변경 이력 (#181)
    po_document,  # 발주서 문서·엑셀 (#157)
    po_mail,  # 발주서 메일 발송 (#158)
    supplier_reply,  # 직원이 받은 공급업체 회신 기록 (#265 PR4)
)
from app.services import purchase_orders as po_service  # 업무 규칙

router = APIRouter(prefix="/purchase-orders")  # 이 파일의 경로는 모두 /purchase-orders 로 시작
log = logging.getLogger(__name__)  # 이 파일의 로그


def one(user, db, order) -> dict:
    """발주서 하나의 응답 {"data": ...}."""
    return {"data": po_service.build_out(user.company_id, db, [order], user.role)[0]}  # 역할: 승인 버튼(allowed_actions)용


@router.get("")  # 목록 (공급업체별 조회는 ?supplier_id=)
def list_orders(
    user: CurrentUser,
    db: DB,
    page: Page,
    supplier_id: QueryId = None,  # 이 공급업체의 발주만
    status: Annotated[PoStatus | None, Query()] = None,  # 이 상태의 발주만
    q: Annotated[str | None, Query(max_length=100)] = None,  # 발주번호 부분 검색
    receipt_due: Annotated[ReceiptDue | None, Query()] = None,  # 발주함 발주의 납기 구간
) -> dict:
    rows, meta = po_service.list_orders(user.company_id, db, page, supplier_id, status, q, receipt_due)
    return {"data": po_service.build_out(user.company_id, db, rows, user.role), "meta": meta}


@router.get("/export")  # 내보내기 (#191). /{order_id} 보다 먼저 선언해야 "export" 를 번호로 읽지 않는다
def export_orders(
    user: CurrentUser,  # 관리자·담당자 둘 다 (단가·금액은 화면에서 이미 보인다)
    db: ReadDB,  # 여러 쪽을 나눠 읽는 동안 한 시점으로 읽는다
    fmt: Annotated[Literal["csv", "xlsx"], Query(alias="format")],  # 파일 형식 (그 밖은 422)
    supplier_id: QueryId = None,  # 아래 네 칸은 목록 경로와 같은 이름·검사
    status: Annotated[PoStatus | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    receipt_due: Annotated[ReceiptDue | None, Query()] = None,
) -> Response:
    return export.orders(user, db, fmt, supplier_id, status, q, receipt_due)  # 회사는 토큰에서


@router.post("", status_code=201)  # 작성 (DRAFT)
def create_order(data: PurchaseOrderCreate, user: CurrentUser, db: DB) -> dict:
    order = po_service.create_order(user.company_id, db, user.id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    return one(user, db, order)


@router.get("/{order_id}")  # 상세
def get_order(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return one(user, db, po_service.get_order(user.company_id, db, order_id))  # 다른 회사 404


@router.get("/{order_id}/change-log")  # 변경 이력 (최신순, 읽기만)
def get_change_log(order_id: PathId, user: CurrentUser, db: DB, page: Page) -> dict:
    rows, meta = po_change_log.list_changes(user.company_id, db, order_id, page)  # 다른 회사 404
    return {"data": [ChangeLogOut(**r).model_dump(mode="json") for r in rows], "meta": meta}


@router.get("/{order_id}/email-log")  # 메일 발송 시도 이력 (최신순, 읽기만, 관리자·담당자 둘 다, #182)
def get_email_log(order_id: PathId, user: CurrentUser, db: DB, page: Page) -> dict:
    rows, meta = po_mail.list_attempts(user.company_id, db, order_id, page)  # 다른 회사 404
    return {"data": [EmailLogOut(**r).model_dump(mode="json") for r in rows], "meta": meta}


@router.get("/{order_id}/document")  # 문서 화면용 값 (승인 이후만, 읽기만 하므로 GET)
def get_document(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return {"data": po_document.build_document(user.company_id, db, order_id)}  # 404·409


@router.get("/{order_id}/document.xlsx")  # 같은 값의 엑셀 파일
def get_document_xlsx(order_id: PathId, user: CurrentUser, db: DB) -> Response:
    doc = po_document.build_document(user.company_id, db, order_id)  # 404·409
    return Response(
        po_document.build_xlsx(doc),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{doc["po_number"]}.xlsx"'},  # 발주번호는 영문·숫자·하이픈뿐
    )


@router.get("/{order_id}/email")  # 메일 미리보기 (APPROVED·ORDERED, 읽기만)
def get_email_preview(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return {"data": po_mail.build_preview(user.company_id, db, user, order_id)}  # 404·409


@router.post("/{order_id}/email")  # 메일 발송 → 성공하면 ORDERED + 발송 기록 (관리자·담당자 둘 다, 주문 완료 표시와 같은 권한)
def send_email(order_id: PathId, data: OrderEmailSend, user: CurrentUser, db: DB) -> dict:
    # 이력(#182)은 모두 이 요청의 세션 하나로 쓴다. 다른 연결로 쓰면, 이 세션이 잠근 발주서를 가리키는 행의 외래키 검사가
    # 잠금이 풀리기를 기다리고 이 세션은 그 연결을 기다려 요청이 멈춘다
    try:
        order, entry = po_mail.send_order(user.company_id, db, user, order_id, data.intro, data.resend)  # 404·409·502·503
    except AppError as exc:
        if exc.code == "MAIL_FAILED":  # 발송 실패: 세션에 든 변경은 실패 이력 1행뿐이다(send_order 가 보장) → 그것만 확정
            try:
                db.commit()
            except Exception:  # noqa: BLE001 — 실패 기록을 못 남겨도 사용자에게는 원래 실패(502)를 알린다
                db.rollback()
                log.warning("메일 실패 이력 저장 실패: purchase_order_id=%s", order_id)  # 주소·토큰은 남기지 않는다
        raise
    try:
        db.commit()  # 확정 (발주서 잠금도 여기서 풀린다)
    except Exception as exc:  # 메일은 이미 나갔는데 저장만 실패한 드문 경우: 다시 보내지 않게 알린다
        db.rollback()  # 잠금이 풀린 뒤라 같은 세션으로 "나갔지만 저장 실패" 1행을 한 번만 남겨 본다
        try:
            db.add(PoEmailLog(**entry, result="UNSAVED"))
            db.commit()
        except Exception:  # noqa: BLE001 — 기록을 못 남겨도 원래 안내(500)를 그대로 낸다
            db.rollback()
            log.warning("메일 UNSAVED 이력 저장 실패: purchase_order_id=%s", order_id)  # 주소·토큰은 남기지 않는다
        # 링크를 넣어 보냈다면 새 토큰도 저장되지 않아 그 링크는 열리지 않는다(#265). 버튼 이름은 document/mail-panel.tsx 와 같게
        link_note = (" 이번 메일의 확인 링크는 열리지 않습니다. 공급업체가 링크로 회신해야 하면 발주함 상태에서 '다시 보내기'를 눌러 주세요."
                     if po_mail.supplier_link_base() else "")
        raise AppError(500, "MAIL_SENT_NOT_SAVED", "메일은 보냈지만 발송 기록을 저장하지 못했습니다. 다시 보내지 말고, "
                       "공급업체에 도착했는지 확인한 뒤 '주문 완료 표시'를 눌러 주세요." + link_note) from exc
    return one(user, db, order)


@router.patch("/{order_id}")  # 수정 (DRAFT 일 때만)
def update_order(order_id: PathId, data: PurchaseOrderUpdate, user: CurrentUser, db: DB) -> dict:
    order = po_service.update_order(user.company_id, db, user.id, order_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정
    return one(user, db, order)


def transition(order_id: int, user, db, action: str, reason: str | None = None) -> dict:
    """상태 변경 세 경로의 공통 부분: 바꾸고, 요청 끝에 한 번 확정하고, 바뀐 발주서를 돌려준다."""
    order = po_service.change_status(user.company_id, db, user.id, order_id, action, reason)  # 404·409
    db.commit()  # 확정 (발주서 잠금도 여기서 풀린다)
    return one(user, db, order)


@router.post("/{order_id}/approve")  # DRAFT → APPROVED (관리자만, 담당자는 403 FORBIDDEN_ROLE)
def approve_order(order_id: PathId, user: AdminUser, db: DB) -> dict:
    return transition(order_id, user, db, "approve")


@router.post("/{order_id}/order")  # APPROVED → ORDERED (공급업체에 발주했음 표시, 둘 다)
def mark_ordered(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return transition(order_id, user, db, "order")


@router.post("/{order_id}/cancel")  # DRAFT·APPROVED·ORDERED → CANCELLED (입고 기록이 없을 때만, 둘 다)
def cancel_order(order_id: PathId, user: CurrentUser, db: DB, data: OrderCancel | None = None) -> dict:
    return transition(order_id, user, db, "cancel", data.reason if data else None)  # 본문은 선택. 발주함 취소는 사유 필수(422)


@router.post("/{order_id}/close-remaining")  # 부분 입고된 ORDERED → RECEIVED (사유 필수, 입고 기록이 있을 때만, 둘 다, #252)
def close_remaining(order_id: PathId, data: OrderCloseRemaining, user: CurrentUser, db: DB) -> dict:
    order = po_service.close_remaining(user.company_id, db, user.id, order_id, data.reason)  # 404·409·422
    db.commit()  # 확정 (발주서 잠금도 여기서 풀린다)
    return one(user, db, order)


@router.post("/{order_id}/supplier-reply")  # 직원이 전화·메일로 받은 공급업체 회신 기록 (ORDERED 만, 둘 다, 상태는 그대로, #265 PR4)
def record_supplier_reply(order_id: PathId, data: SupplierReplyRecord, user: CurrentUser, db: DB) -> dict:
    order = supplier_reply.record_by_staff(user.company_id, db, user.id, order_id, data.due_date, data.reason)  # 404·409·422
    db.commit()  # 확정 (발주서 잠금도 여기서 풀린다). 같은 날짜 재입력은 바뀐 것이 없어 멱등 키가 필요 없다
    return one(user, db, order)


@router.post("/{order_id}/receipts", status_code=201)  # 발주 입고 (ORDERED 일 때만, 부분 가능, 다 차면 RECEIVED)
def receive_order(order_id: PathId, data: ReceiptCreate, user: CurrentUser, db: DB, request: Request,
                  key: IdempotencyKeyHeader = None):
    def work() -> dict:
        order = po_service.receive_order(user.company_id, db, user.id, order_id, data)  # 404·409·422
        db.refresh(order)  # DB 값으로 다시 읽어 시각(received_at)이 커밋 뒤 응답과 같은 모양(UTC)이 되게
        return one(user, db, order)  # 갱신된 상태와 줄별 누적 입고량 (커밋 전에 만들어 멱등 키에 함께 저장)
    return idempotency.run(db, user.company_id, request.url.path, key, data, work)  # 요청 끝에 한 번만 확정: 여러 줄이 함께 저장된다
