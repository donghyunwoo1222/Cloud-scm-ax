"""관리자 로그인 메일 인증코드(#179) 테스트: 정상·만료·5회·재사용·재발송·메일 폭탄·직원·유예·재설정·스위치·동시 제출."""

import logging  # 비상 스위치 경고 확인
import re  # 메일 본문에서 코드 꺼내기
from datetime import UTC, datetime, timedelta  # 고정 시각

import pytest  # 테스트 도구

from app.auth.security import create_otp_token, hash_otp_code  # 해시 비교, 임시 토큰
from app.config import settings  # 메일 설정·비상 스위치
from app.errors import AppError  # 동시 제출 결과 확인
from app.models import User  # 사용자 표
from app.services import login_otp  # 서비스 직접 호출 (동시성·경고)
from tests.concurrency import run_at_once, run_in_new_session  # 진짜 동시 요청
from tests.helpers import PASSWORD  # world 사용자 공통 비밀번호

LOGIN = "/api/v1/auth/login"
VERIFY = "/api/v1/auth/otp/verify"
RESEND = "/api/v1/auth/otp/resend"
T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)  # 고정 시각 12:00
ADMIN = "admin@a.test"  # world 의 회사 A 관리자


@pytest.fixture
def mails(monkeypatch, world, session):
    """메일 설정을 켜고 보낸 메일을 모은다. 시각 12:00 고정. 회사 A 관리자는 유예 없음(즉시 코드 대상)."""
    sent = []
    monkeypatch.setattr(settings, "app_base_url", "http://app.test")
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@test")
    monkeypatch.setattr("app.services.po_mail.deliver", sent.append)  # 실제 발송 대신 목록에 담는다
    monkeypatch.setattr("app.auth.lockout.now", lambda: T0)
    world["a_admin"].otp_grace_until = None
    session.commit()
    return sent


def at(monkeypatch, moment):
    monkeypatch.setattr("app.auth.lockout.now", lambda: moment)  # 현재 시각 이동


def code_of(msg) -> str:
    return re.search(r"\b(\d{6})\b", msg.get_content()).group(1)  # 메일 본문의 6자리


def login(client, email=ADMIN, password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def verify(client, code):
    return client.post(VERIFY, json={"code": code})


def wrong(code: str) -> str:
    return f"{(int(code) + 1) % 10**6:06d}"  # 맞는 코드와 다른 6자리


def test_admin_needs_code_then_logs_in(client, mails):
    """비밀번호만으로는 로그인되지 않고, 메일 코드를 맞히면 정식 쿠키를 받는다. 응답에 코드·이메일이 없다."""
    r = login(client)
    assert r.status_code == 200 and r.json()["data"]["otp_required"] is True
    assert "access_token" not in r.cookies  # 아직 정식 로그인 아님
    assert client.get("/api/v1/me").status_code == 401
    assert len(mails) == 1 and mails[0]["To"] == ADMIN
    code = code_of(mails[0])
    assert code not in r.text and ADMIN not in r.text  # 응답에 코드·이메일 없음
    cookie = r.headers["set-cookie"].lower()
    assert cookie.startswith("otp_pending=") and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/v1/auth/otp" in cookie and "max-age=1800" in cookie  # 30분, 코드 경로에만
    ok = verify(client, code)
    assert ok.status_code == 200 and ok.json()["data"]["email"] == ADMIN
    assert 'otp_pending=""' in ok.headers["set-cookie"]  # 임시 쿠키 삭제
    assert client.get("/api/v1/me").status_code == 200


def test_only_hash_is_stored(client, mails, session):
    """DB 에는 코드 원문이 아니라 HMAC 해시만 있다."""
    login(client)
    code = code_of(mails[0])
    user = session.query(User).filter_by(email=ADMIN).one()
    session.refresh(user)
    assert user.otp_code_hash == hash_otp_code(user.id, code) and code not in user.otp_code_hash
    assert user.otp_sent_at == T0


def test_code_is_single_use(client, mails):
    """한 번 맞힌 코드는 같은 임시 토큰으로 다시 내도 통과하지 않는다."""
    pending = login(client).cookies["otp_pending"]
    code = code_of(mails[0])
    assert verify(client, code).status_code == 200
    again = client.post(VERIFY, json={"code": code}, headers={"Cookie": f"otp_pending={pending}"})
    assert again.status_code == 401 and again.json()["error"]["code"] == "OTP_RESTART"


def test_code_expires_after_10_minutes(client, mails, monkeypatch):
    login(client)
    code = code_of(mails[0])
    at(monkeypatch, T0 + timedelta(minutes=10))  # 정확히 10분 뒤
    r = verify(client, code)
    assert r.status_code == 401 and r.json()["error"]["code"] == "OTP_EXPIRED"


def test_five_wrong_codes_discard_and_lock(client, mails):
    """4번 틀리면 남은 횟수를 알려 주고, 5번째에 폐기된다. 맞는 코드도 더는 안 되고, 잠금(#168)에 걸린다."""
    login(client)
    code = code_of(mails[0])
    for left in (4, 3, 2, 1):
        r = verify(client, wrong(code))
        assert r.status_code == 401 and r.json()["error"]["details"]["attempts_left"] == left
    fifth = verify(client, wrong(code))
    assert fifth.status_code == 401 and fifth.json()["error"]["code"] == "OTP_RESTART"
    assert verify(client, code).status_code == 429  # 5번 실패로 잠김 (코드를 보기 전에 막는다)
    assert login(client).status_code == 429  # 비밀번호 단계도 잠김


def test_resend_interval_limit_and_old_code_dies(client, mails, monkeypatch):
    """재발송은 60초 뒤부터, 로그인당 3번까지. 새 코드를 받으면 이전 코드는 무효."""
    login(client)
    first = code_of(mails[0])
    r = client.post(RESEND)
    assert r.status_code == 429 and r.json()["error"]["code"] == "OTP_RESEND_WAIT" and len(mails) == 1
    for i in range(1, 4):  # 60초마다 3번
        at(monkeypatch, T0 + timedelta(seconds=60 * i))
        assert client.post(RESEND).status_code == 200
    assert len(mails) == 4
    at(monkeypatch, T0 + timedelta(seconds=240))
    fourth = client.post(RESEND)
    assert fourth.status_code == 429 and fourth.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert verify(client, first).json()["error"]["code"] == "OTP_INVALID"  # 첫 코드는 무효
    assert verify(client, code_of(mails[-1])).status_code == 200  # 마지막 코드만 유효


def test_relogin_within_60s_sends_no_new_mail(client, mails, monkeypatch):
    """60초 안에 다시 로그인하면 새 메일 없이 기존 코드가 유효하다고 안내한다 (메일 폭탄 방지)."""
    login(client)
    at(monkeypatch, T0 + timedelta(seconds=30))
    again = login(client)
    assert again.json()["data"]["code_sent"] is False and again.json()["data"]["resend_after"] == 30
    assert len(mails) == 1
    assert verify(client, code_of(mails[0])).status_code == 200  # 기존 코드 그대로
    at(monkeypatch, T0 + timedelta(seconds=90))  # 60초가 지나면 새 로그인 = 새 메일
    client.post("/api/v1/auth/logout")
    assert login(client).json()["data"]["code_sent"] is True and len(mails) == 2


def test_staff_login_unchanged(client, mails, world, session):
    """직원은 유예가 없어도 코드 없이 바로 로그인한다."""
    world["a_staff"].otp_grace_until = None
    session.commit()
    r = login(client, "staff@a.test")
    assert r.status_code == 200 and "access_token" in r.cookies and r.json()["data"]["otp_notice"] is None
    assert mails == []


def test_grace_period_before_and_after(client, mails, world, session, monkeypatch):
    """유예 중에는 코드 없이 로그인하고 안내를 받는다. 유예가 끝나면 코드가 필요하다."""
    world["a_admin"].otp_grace_until = T0 + timedelta(days=14)
    session.commit()
    r = login(client)
    notice = r.json()["data"]["otp_notice"]
    assert r.status_code == 200 and "access_token" in r.cookies and "2026-11-25" in notice
    assert ADMIN not in notice and mails == []
    client.post("/api/v1/auth/logout")
    at(monkeypatch, T0 + timedelta(days=14))  # 유예 종료 시각
    assert login(client).json()["data"]["otp_required"] is True and len(mails) == 1


def test_password_reset_does_not_skip_otp(client, mails, monkeypatch):
    """재설정 후 새 비밀번호로 로그인해도 코드를 거친다. 재설정 전의 임시 토큰은 무효."""
    old_pending = login(client).cookies["otp_pending"]
    client.post("/api/v1/auth/password-reset/request", json={"email": ADMIN})
    token = re.search(r"token=([\w-]+)", mails[-1].get_content()).group(1)
    assert client.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "new-password-1"}).status_code == 200
    stale = client.post(VERIFY, json={"code": code_of(mails[0])}, headers={"Cookie": f"otp_pending={old_pending}"})
    assert stale.status_code == 401  # 비밀번호가 바뀌어 옛 임시 토큰은 무효
    at(monkeypatch, T0 + timedelta(seconds=61))
    assert login(client, password="new-password-1").json()["data"]["otp_required"] is True


def test_failed_login_response_unchanged_for_admin(client, mails):
    """관리자 비밀번호 틀림과 없는 이메일은 여전히 같은 401 이고 메일도 없다."""
    bad = login(client, password="wrong-password")
    unknown = login(client, email="nobody@a.test")
    assert bad.status_code == unknown.status_code == 401 and bad.json() == unknown.json()
    assert mails == []


def test_pending_token_cannot_call_apis(client, mails, world):
    """임시 토큰을 정식 쿠키 자리에 넣어도 401. 정식 토큰을 임시 자리에 넣어도 401."""
    pending = create_otp_token(world["a_admin"].id, world["a_admin"].password_hash)
    assert client.get("/api/v1/me", headers={"Cookie": f"access_token={pending}"}).status_code == 401
    assert verify(client, "000000").status_code == 401  # 임시 쿠키 없이
    assert client.post(RESEND).status_code == 401


def test_logout_clears_pending_cookie(client, mails):
    login(client)
    r = client.post("/api/v1/auth/logout")
    assert any(h.startswith('otp_pending=""') for h in r.headers.get_list("set-cookie"))


def test_mail_not_configured_503_for_admin_only(client, mails, monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "")
    r = login(client)
    assert r.status_code == 503 and r.json()["error"]["code"] == "MAIL_NOT_CONFIGURED"
    assert login(client, "staff@a.test").status_code == 200  # 직원은 상관없음


def test_kill_switch_off_and_on(client, mails, monkeypatch, caplog):
    """ADMIN_OTP_ENABLED=false 면 코드 없이 로그인하고 시작 경고를 남긴다. 켜져 있으면 경고 없음."""
    monkeypatch.setattr(login_otp.log, "disabled", False)  # conftest 의 alembic 로그 설정이 꺼 둔 로거를 다시 켠다
    with caplog.at_level(logging.WARNING, logger="app.services.login_otp"):
        login_otp.warn_if_disabled()
    assert caplog.records == []
    assert login(client).json()["data"]["otp_required"] is True  # 켜짐
    monkeypatch.setattr(settings, "admin_otp_enabled", False)
    with caplog.at_level(logging.WARNING, logger="app.services.login_otp"):
        login_otp.warn_if_disabled()
    assert "ADMIN_OTP_ENABLED=false" in caplog.text
    r = login(client)
    assert r.status_code == 200 and "access_token" in r.cookies  # 꺼짐: 바로 로그인


def test_mail_failure_logs_only_type(monkeypatch, caplog):
    """발송이 실패해도 예외 종류만 남고 코드·주소는 로그에 없다."""
    def boom(msg):
        raise OSError("smtp down admin@a.test 123456")
    monkeypatch.setattr("app.services.po_mail.deliver", boom)
    monkeypatch.setattr(login_otp.log, "disabled", False)  # conftest 의 alembic 로그 설정이 꺼 둔 로거를 다시 켠다
    with caplog.at_level(logging.WARNING, logger="app.services.login_otp"):
        login_otp.send_code_mail(ADMIN, "123456")
    assert "OSError" in caplog.text and "123456" not in caplog.text and ADMIN not in caplog.text


def test_same_code_twice_at_once_only_one_passes(engine, committed_company):
    """같은 코드를 동시에 두 번 내면 행 잠금 때문에 하나만 통과한다."""
    uid = committed_company["admin_id"]
    code = run_in_new_session(engine, lambda s: login_otp.start(s, s.get(User, uid), T0))

    def submit():
        return run_in_new_session(engine, lambda s: login_otp.verify(s, login_otp.lock_user(s, uid), code, T0 + timedelta(seconds=5)))

    results = run_at_once(submit, submit)
    assert results.count(None) == 1  # 한 번만 성공
    failed = [r for r in results if r is not None]
    assert isinstance(failed[0], AppError) and failed[0].code == "OTP_RESTART"
