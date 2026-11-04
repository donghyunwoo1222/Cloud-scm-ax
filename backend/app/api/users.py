"""직원 계정 관리 경로. 모두 관리자 전용(AdminUser), 담당자는 403."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import AdminUser  # 관리자만 통과 (#23)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.common import PathId  # 번호 칸 (DB 범위를 넘으면 422, #71)
from app.schemas.users import UserCreate, UserOut, UserUpdate  # 요청·응답 모양
from app.services import users as users_service  # 업무 규칙

router = APIRouter(prefix="/users")  # 이 파일의 경로는 모두 /users 로 시작


@router.get("")  # 직원 목록
def list_users(
    admin: AdminUser,
    db: DB,
    page: Page,
    include_inactive: Annotated[bool, Query()] = False,  # true 면 비활성 직원도 포함 (기본은 숨김)
) -> dict:
    rows, meta = users_service.list_users(admin.company_id, db, page, include_inactive)  # 회사는 토큰 사용자에게서
    return {"data": [UserOut.model_validate(u).model_dump(mode="json") for u in rows], "meta": meta}  # 목록 모양


@router.post("", status_code=201)  # 직원 계정 생성
def create_user(data: UserCreate, admin: AdminUser, db: DB) -> dict:
    user = users_service.create_user(admin.company_id, db, data)  # 이메일 중복 409, 짧은 비밀번호 422
    return {"data": UserOut.model_validate(user).model_dump(mode="json")}


@router.patch("/{user_id}")  # 역할 변경·비활성
def update_user(user_id: PathId, data: UserUpdate, admin: AdminUser, db: DB) -> dict:
    user = users_service.update_user(admin.company_id, db, user_id, data)  # 다른 회사 404, 마지막 관리자 409
    return {"data": UserOut.model_validate(user).model_dump(mode="json")}
