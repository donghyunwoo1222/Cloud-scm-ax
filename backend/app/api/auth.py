"""회사 가입, 로그인, 로그아웃, 내 정보 경로."""

from fastapi import APIRouter, Response  # 라우터, 응답 객체
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth.deps import COOKIE_NAME, CurrentUser  # 쿠키 이름, 로그인 사용자
from app.auth.security import TOKEN_HOURS, create_token  # 토큰 유효 시간, 토큰 만들기
from app.config import settings  # COOKIE_SECURE
from app.db import DB  # 요청마다 DB 세션
from app.models import Company, User  # 회사, 사용자 표
from app.schemas.auth import CompanyOut, CompanySignup, LoginRequest, MeOut  # 요청·응답 모양
from app.services import auth as auth_service  # 업무 규칙

router = APIRouter()  # 이 파일의 경로 묶음

COOKIE_OPTIONS = {  # 쿠키를 만들 때와 지울 때 똑같이 써야 브라우저가 같은 쿠키로 알아본다
    "httponly": True,  # 화면 자바스크립트가 읽지 못한다
    "samesite": "lax",  # 다른 사이트에서 보낸 POST에는 쿠키가 붙지 않는다
    "secure": settings.cookie_secure,  # 배포(HTTPS)에서만 true
    "path": "/",  # 모든 경로에 쿠키를 보낸다
}


def me_out(db: Session, user: User) -> dict:
    """사용자 → 응답 모양 {"data": 내 정보}."""
    company = db.get(Company, user.company_id)  # 소속 회사
    me = MeOut(
        name=user.name,
        email=user.email,
        role=user.role,
        company=CompanyOut(id=company.id, name=company.name),
    )  # 필요한 칸만 골라 담는다 (password_hash 는 없음)
    return {"data": me.model_dump()}  # 성공 응답 모양


@router.post("/companies", status_code=201)  # 회사 가입 (로그인 전 누구나)
def sign_up(data: CompanySignup, db: DB) -> dict:
    admin = auth_service.create_company(db, data)  # 회사 + 첫 관리자 생성
    return me_out(db, admin)  # 만든 관리자 정보


@router.post("/auth/login")  # 로그인
def login(data: LoginRequest, response: Response, db: DB) -> dict:
    user = auth_service.authenticate(db, data.email, data.password)  # 틀리면 여기서 401
    token = create_token(user.id, user.company_id, user.role)  # 8시간짜리 토큰
    response.set_cookie(COOKIE_NAME, token, max_age=TOKEN_HOURS * 3600, **COOKIE_OPTIONS)  # 쿠키 수명 = 토큰 수명 (8시간 = 28800초)
    return me_out(db, user)  # 로그인한 사용자 정보


@router.post("/auth/logout", status_code=204)  # 로그아웃 (상태를 바꾸므로 POST)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, **COOKIE_OPTIONS)  # 브라우저에 쿠키 삭제를 지시한다


@router.get("/me")  # 내 정보 (읽기만 하므로 GET)
def me(user: CurrentUser, db: DB) -> dict:
    return me_out(db, user)  # 토큰으로 확인한 사용자 정보
