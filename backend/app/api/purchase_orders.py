"""발주서 경로: 작성·수정·조회(#33), 상태 변경 approve·order·cancel(#34), 입고(#35). 승인만 관리자, 나머지는 둘 다."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query, Response  # 라우터, 쿼리 문자열 칸, 파일 응답

from app.auth.deps import AdminUser, CurrentUser  # 관리자만 / 로그인 사용자 (#22·#23)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.common import PathId, QueryId  # 번호 칸 (DB 범위를 넘으면 422, #71)
from app.schemas.purchase_orders import (  # 요청 모양
    PoStatus,
    PurchaseOrderCreate,
    PurchaseOrderUpdate,
    ReceiptCreate,
    ReceiptDue,
)
from app.services import po_document  # 발주서 문서·엑셀 (#157)
from app.services import purchase_orders as po_service  # 업무 규칙

router = APIRouter(prefix="/purchase-orders")  # 이 파일의 경로는 모두 /purchase-orders 로 시작


def one(user, db, order) -> dict:
    """발주서 하나의 응답 {"data": ...}."""
    return {"data": po_service.build_out(user.company_id, db, [order])[0]}


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
    return {"data": po_service.build_out(user.company_id, db, rows), "meta": meta}


@router.post("", status_code=201)  # 작성 (DRAFT)
def create_order(data: PurchaseOrderCreate, user: CurrentUser, db: DB) -> dict:
    order = po_service.create_order(user.company_id, db, user.id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    return one(user, db, order)


@router.get("/{order_id}")  # 상세
def get_order(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return one(user, db, po_service.get_order(user.company_id, db, order_id))  # 다른 회사 404


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


@router.patch("/{order_id}")  # 수정 (DRAFT 일 때만)
def update_order(order_id: PathId, data: PurchaseOrderUpdate, user: CurrentUser, db: DB) -> dict:
    order = po_service.update_order(user.company_id, db, order_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정
    return one(user, db, order)


def transition(order_id: int, user, db, action: str) -> dict:
    """상태 변경 세 경로의 공통 부분: 바꾸고, 요청 끝에 한 번 확정하고, 바뀐 발주서를 돌려준다."""
    order = po_service.change_status(user.company_id, db, user.id, order_id, action)  # 404·409
    db.commit()  # 확정 (발주서 잠금도 여기서 풀린다)
    return one(user, db, order)


@router.post("/{order_id}/approve")  # DRAFT → APPROVED (관리자만, 담당자는 403 FORBIDDEN_ROLE)
def approve_order(order_id: PathId, user: AdminUser, db: DB) -> dict:
    return transition(order_id, user, db, "approve")


@router.post("/{order_id}/order")  # APPROVED → ORDERED (공급업체에 발주했음 표시, 둘 다)
def mark_ordered(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return transition(order_id, user, db, "order")


@router.post("/{order_id}/cancel")  # DRAFT·APPROVED·ORDERED → CANCELLED (입고 기록이 없을 때만, 둘 다)
def cancel_order(order_id: PathId, user: CurrentUser, db: DB) -> dict:
    return transition(order_id, user, db, "cancel")


@router.post("/{order_id}/receipts", status_code=201)  # 발주 입고 (ORDERED 일 때만, 부분 가능, 다 차면 RECEIVED)
def receive_order(order_id: PathId, data: ReceiptCreate, user: CurrentUser, db: DB) -> dict:
    order = po_service.receive_order(user.company_id, db, user.id, order_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정: 여러 줄이 함께 저장된다 (발주서·품목 잠금도 여기서 풀린다)
    return one(user, db, order)  # 갱신된 상태와 줄별 누적 입고량
