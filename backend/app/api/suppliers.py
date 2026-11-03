"""공급업체 경로. 관리자·담당자 모두 사용(CurrentUser). 삭제 경로는 없다(비활성으로 대신)."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.suppliers import SupplierCreate, SupplierOut, SupplierUpdate  # 요청·응답 모양
from app.services import suppliers as suppliers_service  # 업무 규칙

router = APIRouter(prefix="/suppliers")  # 이 파일의 경로는 모두 /suppliers 로 시작


def out(supplier) -> dict:
    return SupplierOut.model_validate(supplier).model_dump(mode="json")  # 응답에 담을 칸만 골라 JSON 으로


@router.get("")  # 목록
def list_suppliers(
    user: CurrentUser,
    db: DB,
    page: Page,
    include_inactive: Annotated[bool, Query()] = False,  # true 면 비활성 포함 (기본은 숨김)
    q: Annotated[str | None, Query(max_length=100)] = None,  # 업체명 검색어
) -> dict:
    rows, meta = suppliers_service.list_suppliers(user.company_id, db, page, include_inactive, q)  # 회사는 토큰 사용자에게서
    return {"data": [out(s) for s in rows], "meta": meta}


@router.post("", status_code=201)  # 등록
def create_supplier(data: SupplierCreate, user: CurrentUser, db: DB) -> dict:
    return {"data": out(suppliers_service.create_supplier(user.company_id, db, data))}  # 같은 이름 409


@router.get("/{supplier_id}")  # 상세
def get_supplier(supplier_id: int, user: CurrentUser, db: DB) -> dict:
    return {"data": out(suppliers_service.get_supplier(user.company_id, db, supplier_id))}  # 다른 회사 404


@router.patch("/{supplier_id}")  # 수정·비활성·다시 활성
def update_supplier(supplier_id: int, data: SupplierUpdate, user: CurrentUser, db: DB) -> dict:
    return {"data": out(suppliers_service.update_supplier(user.company_id, db, supplier_id, data))}  # 다른 회사 404
