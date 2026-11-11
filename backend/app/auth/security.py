"""비밀번호 해시·검사와 로그인 토큰 만들기·풀기. 인증에 쓰는 계산은 모두 여기 한 곳에 둔다."""

import hashlib  # 비밀번호 지문·재설정 토큰 해시
from datetime import UTC, datetime, timedelta  # 만료 시각 계산

import jwt  # PyJWT: 토큰 서명·확인
from argon2 import PasswordHasher  # Argon2id 해시 도구
from argon2.exceptions import InvalidHashError, VerificationError  # 비밀번호 불일치·해시 형식 오류

from app.config import settings  # SECRET_KEY
from app.errors import AppError  # 공통 오류

TOKEN_HOURS = 8  # 토큰 유효 시간. 쿠키 수명(Max-Age)도 같은 값을 쓴다
TOKEN_ALGORITHM = "HS256"  # 서버 비밀키 하나로 서명·확인하는 방식
MIN_PASSWORD_LENGTH = 8  # 비밀번호 최소 길이

_hasher = PasswordHasher()  # 기본 설정(Argon2id)으로 해시 도구 하나
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")  # 없는 이메일일 때도 같은 시간만큼 검사하려고 쓰는 가짜 해시


def validate_password(password: str) -> None:
    """비밀번호 규칙 검사. 회사 가입(#22)과 직원 계정 생성(#24)이 함께 쓴다."""
    if len(password) < MIN_PASSWORD_LENGTH:  # 8자 미만이면
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "비밀번호는 8자 이상이어야 합니다.",
            [{"field": "password", "reason": "too_short"}],  # 어느 칸이 왜 문제인지
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)  # 원문 → "$argon2id$..." (같은 비밀번호도 매번 다른 값, 되돌릴 수 없음)


def verify_password(password: str, password_hash: str | None) -> bool:
    """비밀번호가 맞으면 True. 해시가 없으면(없는 이메일) 가짜 해시로 검사해 걸리는 시간을 맞춘다."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None  # 가짜 해시로는 항상 False
    except (VerificationError, InvalidHashError):  # 틀린 비밀번호, 깨진 해시
        return False


def password_fingerprint(password_hash: str) -> str:
    """비밀번호 해시의 짧은 지문. 토큰에 넣어 두면 비밀번호가 바뀌는 순간 옛 토큰이 맞지 않게 된다 (#170)."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:16]  # 해시의 해시라 토큰을 읽어도 비밀번호 정보는 알 수 없다


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()  # 링크 토큰은 무작위 32바이트라 빠른 해시로 충분하다 (DB에는 이것만 저장)


def create_token(user_id: int, company_id: int, role: str, password_hash: str) -> str:
    """사용자·회사·역할과 만료 시각을 담아 서명한 토큰을 만든다."""
    payload = {
        "user_id": user_id,  # 누구인지
        "company_id": company_id,  # 어느 회사인지 (회사 분리의 근거, R1)
        "role": role,  # ADMIN / STAFF
        "pv": password_fingerprint(password_hash),  # 이 토큰을 발급할 때의 비밀번호 지문 (#170)
        "exp": datetime.now(UTC) + timedelta(hours=TOKEN_HOURS),  # 만료 시각 (지금 + 8시간)
    }
    return jwt.encode(payload, settings.secret_key, algorithm=TOKEN_ALGORITHM)  # 비밀키로 서명한 문자열


def decode_token(token: str) -> dict:
    """서명과 만료를 확인하고 내용을 돌려준다. 위조·만료·형식 오류면 InvalidTokenError."""
    return jwt.decode(
        token,
        settings.secret_key,  # 같은 비밀키로 서명을 확인
        algorithms=[TOKEN_ALGORITHM],  # 이 방식만 허용 (다른 방식으로 바꿔치기한 토큰 거절)
        options={"require": ["exp", "user_id", "company_id", "role", "pv"]},  # 빠진 칸이 있으면 거절
    )
