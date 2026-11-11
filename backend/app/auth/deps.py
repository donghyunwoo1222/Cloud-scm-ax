"""경로 함수가 공통으로 쓰는 로그인 확인 (FastAPI 의존성). #23의 회사 분리·역할 검사는 여기에 붙인다."""

from typing import Annotated  # 타입에 부가 정보(의존성)를 붙이는 도구

import jwt  # 토큰 오류 종류
from fastapi import Depends, Request  # 의존성 주입, 요청 객체

from app.auth.security import decode_token, password_fingerprint  # 토큰 풀기
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.models import User  # 사용자 표

COOKIE_NAME = "access_token"  # 토큰을 담는 쿠키 이름


def unauthenticated(message: str = "로그인이 필요합니다.") -> AppError:
    return AppError(401, "UNAUTHENTICATED", message)  # 401은 이유를 최소한만 알려준다


def get_user_any(request: Request, db: DB) -> User:
    """쿠키의 토큰을 확인해 로그인한 사용자를 돌려준다(비밀번호 변경 전이어도 통과). 문제가 있으면 401."""
    token = request.cookies.get(COOKIE_NAME)  # 브라우저가 자동으로 보낸 쿠키
    if not token:  # 쿠키가 없으면
        raise unauthenticated()
    try:
        payload = decode_token(token)  # 서명·만료 확인
    except jwt.InvalidTokenError:  # 위조, 만료, 형식 오류 모두
        raise unauthenticated() from None
    user = db.get(User, payload["user_id"])  # 토큰 속 사용자를 DB에서 다시 확인
    if user is None or not user.is_active:  # 그사이 비활성이 됐으면 토큰이 남아 있어도 막는다
        raise unauthenticated()
    if payload["pv"] != password_fingerprint(user.password_hash):  # 토큰 발급 뒤 비밀번호가 바뀌었으면(변경·재설정) 옛 토큰은 쓸 수 없다 (#170)
        raise unauthenticated()
    if user.company_id != payload["company_id"]:  # 토큰의 회사와 실제 소속이 다르면 (정상이라면 일어날 수 없음) 믿지 않는다
        raise unauthenticated()
    return user  # 경로 함수에 넘긴다. 회사 분리는 user.company_id(= 토큰의 company_id)로 한다


def get_current_user(user: Annotated[User, Depends(get_user_any)]) -> User:
    """대부분의 경로가 쓰는 로그인 확인. 임시 비밀번호를 아직 안 바꿨으면 403 (#169)."""
    if user.must_change_password:  # 변경 전에는 /me·비밀번호 변경·로그아웃 외에는 서버가 막는다 (화면 이동은 편의일 뿐)
        raise AppError(403, "PASSWORD_CHANGE_REQUIRED", "비밀번호를 먼저 변경해 주세요.")
    return user


AnyUser = Annotated[User, Depends(get_user_any)]  # /me, 비밀번호 변경 경로만 쓴다
CurrentUser = Annotated[User, Depends(get_current_user)]  # 경로 함수에서 `user: CurrentUser` 로 로그인 사용자를 받는다


def require_admin(user: CurrentUser) -> User:
    """관리자 전용 경로용. 로그인은 했지만 담당자(STAFF)면 403."""
    if user.role != "ADMIN":  # 관리자가 아니면
        raise AppError(403, "FORBIDDEN_ROLE", "관리자만 할 수 있는 작업입니다.")
    return user


AdminUser = Annotated[User, Depends(require_admin)]  # 경로 함수에서 `user: AdminUser` 로 쓰면 관리자만 통과한다
