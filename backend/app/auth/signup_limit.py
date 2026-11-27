"""회사 가입 시도 횟수는 가입 트랜잭션보다 먼저 확정한다."""

import hmac
from ipaddress import IPv6Address, ip_address
from math import ceil

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError


def normalize_ip(value: str) -> str:
    if "%" in value:  # 인터페이스 식별자는 프록시 IP 목록의 일부가 아니다.
        raise ValueError("scoped IP")
    address = ip_address(value.strip())
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        return str(address.ipv4_mapped)  # IPv4의 두 표기를 한 주소로 센다.
    return str(address)


def client_ip(request: Request, trusted: int) -> str:
    if trusted:
        headers = request.headers.getlist("x-forwarded-for")
        if len(headers) == 1:  # 중복 헤더는 해석이 모호하다.
            try:
                chain = [normalize_ip(part) for part in headers[0].split(",")]
                return chain[-trusted]  # 오른쪽에서 검증된 홉 수만 거슬러 간다.
            except (ValueError, IndexError):
                pass
    try:
        return normalize_ip(request.client.host) if request.client else "unknown"
    except ValueError:
        return "unknown"  # 소켓 주소를 알 수 없는 요청도 한도를 공유한다.


def check_signup(request: Request, db: Session) -> None:
    if not settings.signup_rate_limit_enabled:
        return
    address = client_ip(request, settings.trusted_proxy_count)
    key = hmac.digest(settings.secret_key.encode(), f"signup:{address}".encode(), "sha256")
    # PK 충돌 시 PostgreSQL이 같은 IP의 갱신을 직렬화한다. 만료 시 새 창의 첫 시도로 바꾼다.
    accepted = db.scalar(text("""
        INSERT INTO signup_rate_limits AS s (ip_hash, attempts, expires_at)
        VALUES (:key, 1, now() + make_interval(secs => :seconds))
        ON CONFLICT (ip_hash) DO UPDATE SET
            attempts = CASE WHEN s.expires_at <= now() THEN 1 ELSE s.attempts + 1 END,
            expires_at = CASE WHEN s.expires_at <= now() THEN EXCLUDED.expires_at ELSE s.expires_at END
        WHERE s.expires_at <= now() OR s.attempts < :maximum
        RETURNING attempts
    """), {"key": key, "seconds": settings.signup_rate_limit_window_seconds,
           "maximum": settings.signup_rate_limit_max_attempts})
    if accepted is None:
        # 충돌 행의 잠금을 가진 동안 실제 만료까지 남은 시간을 읽는다.
        remaining = db.scalar(text("""
            SELECT EXTRACT(EPOCH FROM expires_at - clock_timestamp())
            FROM signup_rate_limits WHERE ip_hash = :key
        """), {"key": key})
        db.rollback()
        raise AppError(429, "TOO_MANY_ATTEMPTS", "가입 요청이 많습니다. 잠시 후 다시 시도해 주세요.",
                       headers={"Retry-After": str(max(1, ceil(remaining)))})
    db.commit()  # 뒤에서 회사 생성이 실패해도 가입 시도는 남긴다.
