"""발주서 경로 (#33: 작성·수정·조회). 관리자·담당자 모두 사용. 승인·발주·취소(#34)와 입고(#35)는 아직 없다."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.purchase_orders import PurchaseOrderCreate, PurchaseOrderUpdate  # 요청 모양
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
    supplier_id: Annotated[int | None, Query()] = None,  # 이 공급업체의 발주만
) -> dict:
    rows, meta = po_service.list_orders(user.company_id, db, page, supplier_id)  # 회사는 토큰 사용자에게서
    return {"data": po_service.build_out(user.company_id, db, rows), "meta": meta}


@router.post("", status_code=201)  # 작성 (DRAFT)
def create_order(data: PurchaseOrderCreate, user: CurrentUser, db: DB) -> dict:
    order = po_service.create_order(user.company_id, db, user.id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    return one(user, db, order)


@router.get("/{order_id}")  # 상세
def get_order(order_id: int, user: CurrentUser, db: DB) -> dict:
    return one(user, db, po_service.get_order(user.company_id, db, order_id))  # 다른 회사 404


@router.patch("/{order_id}")  # 수정 (DRAFT 일 때만)
def update_order(order_id: int, data: PurchaseOrderUpdate, user: CurrentUser, db: DB) -> dict:
    order = po_service.update_order(user.company_id, db, order_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정
    return one(user, db, order)
