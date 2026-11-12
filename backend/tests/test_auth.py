"""회사 가입·로그인·로그아웃·/me 테스트 (쿠키 인증)."""

from datetime import UTC, datetime, timedelta  # 만료된 토큰 만들기

import jwt  # 테스트에서 직접 토큰을 만들어 본다

from app.auth.deps import COOKIE_NAME  # 쿠키 이름
from app.config import settings  # 진짜 서명 키 (만료 토큰 테스트용)
from app.db import get_db  # 테스트 세션을 꺼내는 열쇠
from app.main import app  # 끼워 둔 테스트 세션 찾기
from app.models import User  # 사용자 표
from tests.helpers import GRACE_UNTIL  # 관리자 유예 종료 시각 (#179)

SIGNUP = {  # 기본 가입 요청
    "company_name": "가나상사",
    "admin_name": "김관리",
    "email": "Admin@GaNa.com",  # 대문자가 섞여도 소문자로 저장된다
    "password": "correct-horse",  # 13자
}
LOGIN_FAILED = "이메일 또는 비밀번호가 올바르지 않습니다."  # 로그인 실패 공통 문장


def sign_up(client, **override):
    response = client.post("/api/v1/companies", json={**SIGNUP, **override})  # 가입 요청
    if response.status_code == 201:  # 새 관리자는 처음부터 메일 코드 대상(#179). 이 파일은 비밀번호 로그인을 보므로 유예 중으로 둔다
        session = app.dependency_overrides[get_db]()  # client fixture 가 끼운 테스트 세션
        session.query(User).filter_by(email=response.json()["data"]["email"]).update({"otp_grace_until": GRACE_UNTIL})
        session.commit()
    return response


def login(client, email="admin@gana.com", password="correct-horse"):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})  # 로그인 요청


def assert_401(response, message=None):
    """401 UNAUTHENTICATED 모양인지 확인한다."""
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    if message:  # 문장까지 확인할 때
        assert response.json()["error"]["message"] == message


def test_signup_login_me(client):
    """가입 → 로그인 → /me 200. 비밀번호 해시는 응답 어디에도 없다."""
    assert sign_up(client).status_code == 201  # 회사 + 관리자 생성
    assert login(client).status_code == 200  # 로그인 성공 (쿠키를 받는다)
    response = client.get("/api/v1/me")  # 받은 쿠키로 내 정보 요청
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["email"] == "admin@gana.com"  # 소문자로 정리돼 있다
    assert data["role"] == "ADMIN"  # 첫 계정은 관리자
    assert data["company"]["name"] == "가나상사"  # 소속 회사
    assert "password_hash" not in response.text  # password_hash 칸이 응답에 없다 (must_change_password 표시는 있다)


def test_login_cookie_flags(client):
    """로그인 쿠키에 HttpOnly, SameSite=Lax, 8시간 수명이 붙는다."""
    sign_up(client)
    cookie = login(client).headers["set-cookie"].lower()  # 서버가 보낸 쿠키 설정 줄
    assert cookie.startswith(f"{COOKIE_NAME}=")  # 토큰 쿠키
    assert "httponly" in cookie  # 화면 스크립트가 못 읽는다
    assert "samesite=lax" in cookie  # 다른 사이트의 POST에는 안 붙는다
    assert "max-age=28800" in cookie  # 8시간 × 3600초 = 토큰 수명과 같다
    assert "secure" not in cookie  # 로컬(COOKIE_SECURE=false)에서는 Secure 없음


def test_wrong_password_and_unknown_email_get_same_401(client):
    """틀린 비밀번호와 없는 이메일은 같은 401 문장 (어느 쪽이 틀렸는지 알려주지 않는다)."""
    sign_up(client)
    wrong_password = login(client, password="wrong-password")  # 비밀번호만 틀림
    unknown_email = login(client, email="nobody@gana.com")  # 없는 이메일
    assert_401(wrong_password, LOGIN_FAILED)
    assert_401(unknown_email, LOGIN_FAILED)
    assert wrong_password.json() == unknown_email.json()  # 응답 본문이 완전히 같다


def test_inactive_user_cannot_login(client, session):
    """비활성 사용자는 비밀번호가 맞아도 같은 401."""
    sign_up(client)
    session.query(User).filter_by(email="admin@gana.com").update({"is_active": False})  # 비활성으로 바꾼다
    assert_401(login(client), LOGIN_FAILED)


def test_me_without_cookie(client):
    """쿠키 없이 /me → 401."""
    assert_401(client.get("/api/v1/me"))


def test_framework_errors_use_error_shape(client):
    """없는 경로·이메일 형식 오류도 {"error": {...}} 모양으로 온다."""
    assert client.get("/api/v1/nope").json()["error"]["code"] == "NOT_FOUND"  # 없는 경로
    bad = login(client, email="no-at-sign")  # @ 가 없는 이메일
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad.json()["error"]["details"][0]["field"] == "email"  # 어느 칸이 문제인지


def test_me_with_forged_token(client):
    """다른 키로 서명한 위조 토큰 → 401."""
    sign_up(client)
    login(client)  # 진짜 쿠키를 받아 둔 상태에서
    forged = jwt.encode(  # 내용은 그럴듯하지만 서버 비밀키를 모르는 사람이 만든 토큰
        {"user_id": 1, "company_id": 1, "role": "ADMIN", "exp": datetime.now(UTC) + timedelta(hours=1)},
        "attacker-guess-attacker-guess-1234",  # 서버 비밀키가 아닌 다른 키 (32자 이상)
        algorithm="HS256",
    )
    client.cookies.clear()  # 진짜 쿠키를 지우고
    client.cookies.set(COOKIE_NAME, forged)  # 위조 토큰으로 바꿔치기
    assert_401(client.get("/api/v1/me"))


def test_me_with_expired_token(client, session):
    """진짜 키로 서명했어도 만료 시각이 지났으면 → 401."""
    sign_up(client)
    user = session.query(User).filter_by(email="admin@gana.com").one()  # 실제 사용자
    expired = jwt.encode(
        {"user_id": user.id, "company_id": user.company_id, "role": "ADMIN", "exp": datetime.now(UTC) - timedelta(seconds=1)},  # 1초 전에 만료
        settings.secret_key,
        algorithm="HS256",
    )
    client.cookies.set(COOKIE_NAME, expired)
    assert_401(client.get("/api/v1/me"))


def test_logout_then_me(client):
    """로그아웃 → 쿠키가 지워져 /me 401."""
    sign_up(client)
    login(client)
    assert client.get("/api/v1/me").status_code == 200  # 로그아웃 전에는 된다
    assert client.post("/api/v1/auth/logout").status_code == 204  # 로그아웃
    assert_401(client.get("/api/v1/me"))  # 이제 안 된다


def test_duplicate_email_signup(client):
    """같은 이메일로 두 번 가입 → 409 EMAIL_TAKEN (대소문자만 달라도 같은 이메일)."""
    assert sign_up(client).status_code == 201
    response = sign_up(client, company_name="다른회사", email="admin@gana.COM")  # 대소문자만 다름
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_short_password_rejected(client):
    """비밀번호 7자 → 422 VALIDATION_ERROR, 회사도 만들어지지 않는다."""
    response = sign_up(client, password="1234567")  # 7자
    assert response.status_code == 422
    assert response.json()["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "비밀번호는 8자 이상이어야 합니다.",
        "details": [{"field": "password", "reason": "too_short"}],
    }
    assert login(client, password="1234567").status_code == 401  # 계정이 생기지 않았다


def fix_time(monkeypatch, moment):
    """로그인 제한이 쓰는 현재 시각을 고정한다."""
    monkeypatch.setattr("app.auth.lockout.now", lambda: moment)


T0 = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)  # 테스트용 고정 시각 (12:00)


def test_lockout_after_5_failures_then_unlocks(client, monkeypatch):
    """5번 틀리면 15분 잠금: 맞는 비밀번호도 429, 15분 뒤 성공."""
    sign_up(client)
    fix_time(monkeypatch, T0)
    for _ in range(4):  # 1~4번째 실패는 그냥 401
        assert_401(login(client, password="wrong-password"), LOGIN_FAILED)
    assert_401(login(client, password="wrong-password"), LOGIN_FAILED)  # 5번째 실패: 이 응답은 401, 이후부터 잠김
    fix_time(monkeypatch, T0 + timedelta(minutes=10))
    locked = login(client)  # 맞는 비밀번호여도
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    fix_time(monkeypatch, T0 + timedelta(minutes=15))  # 잠금 해제 시각
    assert login(client).status_code == 200  # 풀렸다


def test_lockout_message_same_for_unknown_email(client, monkeypatch):
    """없는 이메일도 똑같이 5번째 뒤 잠기고 응답 본문이 같다 (잠김 여부로 가입 여부를 알 수 없다)."""
    sign_up(client)
    fix_time(monkeypatch, T0)
    for _ in range(5):
        login(client, password="wrong-password")  # 있는 이메일
        login(client, email="nobody@gana.com")  # 없는 이메일
    real = login(client, password="wrong-password")
    fake = login(client, email="nobody@gana.com")
    assert real.status_code == fake.status_code == 429
    assert real.json() == fake.json()


def test_success_resets_failure_count(client, monkeypatch):
    """4번 실패 후 성공하면 횟수가 0이 되어, 다시 4번 틀려도 잠기지 않는다."""
    sign_up(client)
    fix_time(monkeypatch, T0)
    for _ in range(4):
        login(client, password="wrong-password")
    assert login(client).status_code == 200  # 성공 → 0으로
    for _ in range(4):
        assert_401(login(client, password="wrong-password"), LOGIN_FAILED)  # 여전히 401 (잠기지 않음)


def test_old_failures_are_forgotten(client, monkeypatch):
    """4번 실패 뒤 15분이 지나면 새로 센다: 1번 더 틀려도 잠기지 않는다."""
    sign_up(client)
    fix_time(monkeypatch, T0)
    for _ in range(4):
        login(client, password="wrong-password")
    fix_time(monkeypatch, T0 + timedelta(minutes=16))
    assert_401(login(client, password="wrong-password"), LOGIN_FAILED)  # 5번째지만 새로 1번째
    assert login(client).status_code == 200
