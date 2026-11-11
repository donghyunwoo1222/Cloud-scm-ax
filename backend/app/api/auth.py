"""회사 가입, 로그인, 로그아웃, 내 정보 경로."""

from fastapi import APIRouter, BackgroundTasks, Response  # 라우터, 응답 객체
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth import lockout  # 로그인 시도 제한
from app.auth.deps import COOKIE_NAME, AnyUser  # 쿠키 이름, 로그인 사용자
from app.auth.security import TOKEN_HOURS, create_token  # 토큰 유효 시간, 토큰 만들기
from app.config import settings  # COOKIE_SECURE
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.models import Company, User  # 회사, 사용자 표
from app.schemas.auth import (  # 요청·응답 모양
    CompanyOut,
    CompanySignup,
    LoginRequest,
    MeOut,
    PasswordChange,
    ResetConfirm,
    ResetRequest,
)
from app.services import auth as auth_service  # 업무 규칙
from app.services import password_reset  # 재설정 링크 (#170)

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
        must_change_password=user.must_change_password,  # 변경 전이면 참
    )  # 필요한 칸만 골라 담는다 (password_hash 는 없음)
    return {"data": me.model_dump()}  # 성공 응답 모양


@router.post("/companies", status_code=201)  # 회사 가입 (로그인 전 누구나)
def sign_up(data: CompanySignup, db: DB) -> dict:
    admin = auth_service.create_company(db, data)  # 회사 + 첫 관리자 생성
    return me_out(db, admin)  # 만든 관리자 정보


@router.post("/auth/login")  # 로그인
def login(data: LoginRequest, response: Response, db: DB) -> dict:
    at = lockout.now()  # 이번 요청의 시각 (한 요청 안에서 같은 값을 쓴다)
    lockout.check_not_locked(data.email, at)  # 잠금 중이면 비밀번호를 검사하기 전에 429
    try:
        user = auth_service.authenticate(db, data.email, data.password)  # 틀리면 401
    except AppError:  # 없는 이메일·틀린 비밀번호·비활성 모두
        lockout.record_failure(data.email, at)  # 실패 횟수를 올린다 (이메일이 있든 없든 똑같이)
        raise
    lockout.record_success(data.email)  # 성공: 횟수를 0으로
    token = create_token(user.id, user.company_id, user.role, user.password_hash)  # 8시간짜리 토큰
    response.set_cookie(COOKIE_NAME, token, max_age=TOKEN_HOURS * 3600, **COOKIE_OPTIONS)  # 쿠키 수명 = 토큰 수명 (8시간 = 28800초)
    return me_out(db, user)  # 로그인한 사용자 정보


@router.post("/auth/logout", status_code=204)  # 로그아웃 (상태를 바꾸므로 POST)
def logout(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, **COOKIE_OPTIONS)  # 브라우저에 쿠키 삭제를 지시한다


@router.post("/auth/password")  # 비밀번호 변경 (임시 비밀번호 변경 전에도 쓸 수 있어야 하므로 AnyUser)
def change_password(data: PasswordChange, user: AnyUser, response: Response, db: DB) -> dict:
    at = lockout.now()  # 이번 요청의 시각
    lockout.check_not_locked(user.email, at)  # 현재 비밀번호 추측도 로그인과 같은 잠금을 쓴다
    try:
        auth_service.change_password(db, user, data.current_password, data.new_password)  # 틀리면 401, 규칙 위반 422
    except AppError as e:
        if e.code == "WRONG_CURRENT_PASSWORD":  # 현재 비밀번호가 틀린 경우만 실패로 센다
            lockout.record_failure(user.email, at)
        raise
    lockout.record_success(user.email)  # 맞게 입력했으면 실패 횟수를 0으로
    token = create_token(user.id, user.company_id, user.role, user.password_hash)  # 비밀번호가 바뀌어 옛 토큰은 무효이므로 새 토큰으로 로그인 상태를 이어 준다
    response.set_cookie(COOKIE_NAME, token, max_age=TOKEN_HOURS * 3600, **COOKIE_OPTIONS)  # 쿠키도 새 토큰으로
    return me_out(db, user)  # 표시가 꺼진 내 정보


@router.post("/auth/password-reset/request")  # 재설정 메일 요청 (로그인 전, 누구나)
def request_password_reset(data: ResetRequest, background: BackgroundTasks, db: DB) -> dict:
    password_reset.ensure_ready()  # 서버 설정이 없으면 503
    lockout.allow_reset_request(data.email, lockout.now())  # 같은 이메일 15분 3번 (없는 이메일도 똑같이 센다)
    issued = password_reset.issue_token(db, data.email)  # 없는 이메일이면 None
    if issued:  # 메일은 응답을 보낸 뒤에 발송해 걸리는 시간으로 존재 여부가 드러나지 않게 한다
        background.add_task(password_reset.send_reset_mail, *issued)
    return {"data": {"message": password_reset.SENT_MESSAGE}}  # 있든 없든 같은 응답


@router.post("/auth/password-reset/confirm")  # 새 비밀번호 정하기 (링크의 토큰이 인증 수단)
def confirm_password_reset(data: ResetConfirm, db: DB) -> dict:
    password_reset.confirm_reset(db, data.token, data.new_password, lockout.now())  # 틀린·만료 400, 짧은 비밀번호 422
    return {"data": {"message": "비밀번호를 바꿨습니다. 새 비밀번호로 로그인해 주세요."}}


@router.get("/me")  # 내 정보 (읽기만 하므로 GET)
def me(user: AnyUser, db: DB) -> dict:
    return me_out(db, user)  # 토큰으로 확인한 사용자 정보
