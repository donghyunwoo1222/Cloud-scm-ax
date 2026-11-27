"""가입 API, 프록시 주소 선택, 실제 독립 DB 연결의 경합을 검사한다."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.signup_limit import check_signup, client_ip
from app.config import Settings, settings
from app.errors import AppError
from tests.test_auth import SIGNUP


def request_with(*values):
    return Request({"type": "http", "client": ("192.0.2.40", 443),
                    "headers": [(b"x-forwarded-for", value.encode()) for value in values]})


@pytest.mark.parametrize(("hops", "values", "expected"), [
    (0, ["198.51.100.9"], "192.0.2.40"),
    (1, [], "192.0.2.40"),
    (2, ["198.51.100.9"], "192.0.2.40"),
    (1, ["bad, 198.51.100.9"], "192.0.2.40"),
    (1, ["198.51.100.9,"], "192.0.2.40"),
    (1, ["198.51.100.9", "2001:db8::1"], "192.0.2.40"),
    (2, ["203.0.113.77, 2001:0db8::1, 192.0.2.1"], "2001:db8::1"),
    (1, ["203.0.113.77, ::ffff:198.51.100.9"], "198.51.100.9"),
])
def test_client_ip(hops, values, expected):
    assert client_ip(request_with(*values), hops) == expected


@pytest.mark.parametrize(("field", "value"), [
    ("signup_rate_limit_enabled", "maybe"), ("signup_rate_limit_window_seconds", 0),
    ("signup_rate_limit_max_attempts", -1), ("trusted_proxy_count", -1),
])
def test_invalid_settings(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "signup_rate_limit_enabled", True)
    monkeypatch.setattr(settings, "signup_rate_limit_max_attempts", 2)
    monkeypatch.setattr(settings, "signup_rate_limit_window_seconds", 300)
    monkeypatch.setattr(settings, "trusted_proxy_count", 1)


def test_signup_quota(client, session, enabled):
    def post(chain, email):
        return client.post("/api/v1/companies", json={**SIGNUP, "email": email},
                           headers={"X-Forwarded-For": chain})

    first_ip = "2001:db8::1"
    assert post(first_ip, "one@example.org").status_code == 201
    assert post(first_ip, "one@example.org").status_code == 409  # 실패해도 시도 한 번을 쓴다.
    blocked = post("203.0.113.88, " + first_ip, "two@example.org")
    assert blocked.status_code == 429
    assert 1 <= int(blocked.headers["Retry-After"]) <= 300
    assert blocked.json()["error"] == {"code": "TOO_MANY_ATTEMPTS",
                                       "message": "가입 요청이 많습니다. 잠시 후 다시 시도해 주세요.", "details": None}
    assert post("2001:db8::2", "two@example.org").status_code == 201
    session.execute(text("UPDATE signup_rate_limits SET expires_at = now() - interval '1 second'"))
    session.commit()
    assert post(first_ip, "three@example.org").status_code == 201


def test_concurrent_signup_slots(engine, enabled):
    workers = 6
    barrier = Barrier(workers)

    def attempt(_):
        with Session(engine) as session:
            barrier.wait(timeout=15)  # 서로 다른 연결에서 같은 IP의 첫 행을 동시에 만든다.
            try:
                check_signup(request_with("198.51.100.99"), session)
            except AppError as exc:
                return exc.status
            return 200

    with ThreadPoolExecutor(max_workers=workers) as pool:
        assert sorted(pool.map(attempt, range(workers))) == [200, 200, 429, 429, 429, 429]
