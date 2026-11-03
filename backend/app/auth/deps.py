"""경로 함수가 공통으로 쓰는 로그인 확인 (FastAPI 의존성). #23의 회사 분리·역할 검사는 여기에 붙인다."""

from typing import Annotated  # 타입에 부가 정보(의존성)를 붙이는 도구

import jwt  # 토큰 오류 종류
from fastapi import Depends, Request  # 의존성 주입, 요청 객체

from app.auth.security import decode_token  # 토큰 풀기
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.models import User  # 사용자 표

COOKIE_NAME = "access_token"  # 토큰을 담는 쿠키 이름


def unauthenticated(message: str = "로그인이 필요합니다.") -> AppError:
    return AppError(401, "UNAUTHENTICATED", message)  # 401은 이유를 최소한만 알려준다


def get_current_user(request: Request, db: DB) -> User:
    """쿠키의 토큰을 확인해 로그인한 사용자를 돌려준다. 문제가 있으면 401."""
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
    return user  # 경로 함수에 넘긴다


CurrentUser = Annotated[User, Depends(get_current_user)]  # 경로 함수에서 `user: CurrentUser` 로 로그인 사용자를 받는다
