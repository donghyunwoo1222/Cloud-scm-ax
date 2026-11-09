"""회사 정보 경로. 조회는 로그인한 모두, 수정은 관리자만. 경로에 회사 번호가 없다(토큰의 회사만)."""

from fastapi import APIRouter

from app.auth.deps import AdminUser, CurrentUser
from app.db import DB
from app.schemas.companies import CompanyOut, CompanyUpdate
from app.services import companies as companies_service

router = APIRouter(prefix="/company")  # /company 한 곳만 있다 (남의 회사를 가리킬 방법이 없다)


@router.get("")  # 우리 회사 정보
def get_company(user: CurrentUser, db: DB) -> dict:
    return {"data": CompanyOut.model_validate(companies_service.get_company(user.company_id, db)).model_dump(mode="json")}


@router.patch("")  # 수정 (관리자만, 담당자 403)
def update_company(data: CompanyUpdate, admin: AdminUser, db: DB) -> dict:
    company = companies_service.update_company(admin.company_id, db, data)
    return {"data": CompanyOut.model_validate(company).model_dump(mode="json")}
