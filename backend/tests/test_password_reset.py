"""비밀번호 재설정(#170) 테스트: 링크 1회용·만료·해시 저장·요청 제한·옛 로그인 토큰 무효."""

import re  # 보낸 메일에서 링크 토큰 꺼내기
from datetime import UTC, datetime, timedelta  # 고정 시각

import pytest  # 테스트 도구

from app.auth.security import hash_reset_token  # 저장된 해시와 비교
from app.config import settings  # 메일 설정 (테스트에서 켠다)
from app.models import User  # 사용자 표
from tests.helpers import PASSWORD  # world 사용자 공통 비밀번호

REQUEST = "/api/v1/auth/password-reset/request"
CONFIRM = "/api/v1/auth/password-reset/confirm"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)  # 고정 시각 12:00
EMAIL = "staff@a.test"  # world 의 회사 A 담당자


@pytest.fixture
def mails(monkeypatch):
    """메일 설정을 켜고, 실제 발송 대신 보낸 메일을 모아 두는 목록을 돌려준다. 시각은 12:00 으로 고정."""
    sent = []
    monkeypatch.setattr(settings, "app_base_url", "http://app.test")
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@test")
    monkeypatch.setattr("app.services.po_mail.deliver", sent.append)  # 발송 함수를 가짜로
    monkeypatch.setattr("app.auth.lockout.now", lambda: T0)
    return sent


def token_of(msg) -> str:
    return re.search(r"token=([\w-]+)", msg.get_content()).group(1)  # 메일 본문 링크의 토큰


def at(monkeypatch, moment):
    monkeypatch.setattr("app.auth.lockout.now", lambda: moment)  # 현재 시각 이동


def login(client, password=PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": EMAIL, "password": password})


def test_request_sends_mail_and_stores_only_hash(client, world, session, mails):
    """요청하면 메일이 가고, DB에는 토큰 원본이 아니라 해시와 30분 뒤 만료만 저장된다."""
    response = client.post(REQUEST, json={"email": EMAIL})
    assert response.status_code == 200
    assert len(mails) == 1 and mails[0]["To"] == EMAIL
    token = token_of(mails[0])
    user = session.query(User).filter_by(email=EMAIL).one()
    assert user.reset_token_hash == hash_reset_token(token) != token  # 해시만 저장
    assert user.reset_expires_at == T0 + timedelta(minutes=30)


def test_unknown_email_same_response_and_no_mail(client, world, mails):
    """없는 이메일도 같은 응답(본문 동일)이고 메일은 가지 않는다."""
    real = client.post(REQUEST, json={"email": EMAIL})
    fake = client.post(REQUEST, json={"email": "nobody@a.test"})
    assert real.status_code == fake.status_code == 200
    assert real.json() == fake.json()
    assert len(mails) == 1  # 있는 이메일에만


def test_token_is_single_use_and_old_login_token_dies(client, world, mails, monkeypatch):
    """링크로 비밀번호를 바꾸면 옛 비밀번호는 끝, 이전에 로그인해 둔 토큰은 401, 링크 재사용은 400."""
    assert login(client).status_code == 200  # 12:00 에 로그인해 둔 세션
    client.post(REQUEST, json={"email": EMAIL})
    token = token_of(mails[0])
    at(monkeypatch, T0 + timedelta(minutes=10))
    done = client.post(CONFIRM, json={"token": token, "new_password": "brand-new-pass"})
    assert done.status_code == 200
    assert client.get("/api/v1/me").status_code == 401  # 옛 로그인 토큰 무효
    again = client.post(CONFIRM, json={"token": token, "new_password": "another-pass-1"})
    assert (again.status_code, again.json()["error"]["code"]) == (400, "INVALID_RESET_TOKEN")  # 한 번만
    assert login(client).status_code == 401  # 옛 비밀번호
    assert login(client, "brand-new-pass").status_code == 200  # 새 비밀번호


def test_expired_token_rejected(client, world, mails, monkeypatch):
    """30분이 지나면 400 (정확히 30분 시점도 만료)."""
    client.post(REQUEST, json={"email": EMAIL})
    token = token_of(mails[0])
    at(monkeypatch, T0 + timedelta(minutes=30))
    assert client.post(CONFIRM, json={"token": token, "new_password": "brand-new-pass"}).status_code == 400


def test_new_request_invalidates_previous_link(client, world, mails):
    """새 링크를 요청하면 이전 링크는 무효."""
    client.post(REQUEST, json={"email": EMAIL})
    client.post(REQUEST, json={"email": EMAIL})
    first, second = token_of(mails[0]), token_of(mails[1])
    assert client.post(CONFIRM, json={"token": first, "new_password": "brand-new-pass"}).status_code == 400
    assert client.post(CONFIRM, json={"token": second, "new_password": "brand-new-pass"}).status_code == 200


def test_short_password_keeps_link_usable(client, world, mails):
    """8자 미만이면 422 이고 링크는 그대로 쓸 수 있다."""
    client.post(REQUEST, json={"email": EMAIL})
    token = token_of(mails[0])
    assert client.post(CONFIRM, json={"token": token, "new_password": "short"}).status_code == 422
    assert client.post(CONFIRM, json={"token": token, "new_password": "long-enough-1"}).status_code == 200


def test_request_rate_limit_same_for_unknown_email(client, world, mails, monkeypatch):
    """같은 이메일로 15분에 3번까지, 4번째는 429 (없는 이메일도 똑같이). 15분 뒤에는 다시 된다."""
    for email in (EMAIL, "nobody@a.test"):
        for _ in range(3):
            assert client.post(REQUEST, json={"email": email}).status_code == 200
        assert client.post(REQUEST, json={"email": email}).status_code == 429
    at(monkeypatch, T0 + timedelta(minutes=15))
    assert client.post(REQUEST, json={"email": EMAIL}).status_code == 200


def test_not_configured_returns_503(client, world, monkeypatch):
    """링크 주소·메일 설정이 없으면 이메일과 상관없이 503."""
    monkeypatch.setattr(settings, "app_base_url", "")
    assert client.post(REQUEST, json={"email": EMAIL}).status_code == 503
    assert client.post(REQUEST, json={"email": "nobody@a.test"}).status_code == 503


def test_reset_clears_must_change_and_lock(client, world, session, mails):
    """재설정하면 변경 필요 표시와 로그인 잠금이 풀린다."""
    session.query(User).filter_by(email=EMAIL).update({"must_change_password": True})
    for _ in range(5):
        login(client, "wrong-password")  # 5번 틀려 잠김
    assert login(client).status_code == 429
    client.post(REQUEST, json={"email": EMAIL})
    client.post(CONFIRM, json={"token": token_of(mails[0]), "new_password": "brand-new-pass"})
    ok = login(client, "brand-new-pass")
    assert ok.status_code == 200
    assert ok.json()["data"]["must_change_password"] is False
