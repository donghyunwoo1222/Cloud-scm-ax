"""운영 모드 시작 점검(validate_production_settings)과 시드 실행 점검(check_seed_allowed) 표 테스트."""

import pytest  # 테스트 도구
from pydantic import ValidationError  # 설정 검사 실패

from app.config import Settings, validate_production_settings
from scripts.seed import check_seed_allowed

GOOD = {  # production 에서 모두 통과하는 값 한 벌
    "app_env": "production", "database_url": "postgresql+psycopg://scm:Str0ng-real@dbhost:5432/scm",
    "secret_key": "x" * 40, "cookie_secure": True, "admin_otp_enabled": True, "smtp_host": "smtp.example.com",
    "smtp_security": "starttls", "app_base_url": "https://scm.example.com",
}


def make(**over):
    return Settings.model_construct(**{**GOOD, **over})  # 검사 없이 만든 설정 (순수 함수만 시험)


def test_all_good_has_no_problems():
    assert validate_production_settings(make()) == []


@pytest.mark.parametrize("over,word", [
    ({"cookie_secure": False}, "COOKIE_SECURE"),
    ({"secret_key": "change-me" + "x" * 30}, "SECRET_KEY"),
    ({"smtp_host": ""}, "SMTP_HOST"),
    ({"smtp_security": "none"}, "SMTP_SECURITY"),
    ({"app_base_url": ""}, "APP_BASE_URL"),
    ({"app_base_url": "http://scm.example.com"}, "APP_BASE_URL"),
    ({"database_url": "postgresql+psycopg://scm:scm_local_pw@db:5432/scm"}, "DATABASE_URL"),
])
def test_each_violation_is_reported(over, word):
    problems = validate_production_settings(make(**over))
    assert len(problems) == 1 and word in problems[0]


def test_otp_off_skips_smtp_rules():
    assert validate_production_settings(make(admin_otp_enabled=False, smtp_host="", smtp_security="none")) == []


def test_development_is_not_checked():
    bad = make(app_env="development", cookie_secure=False, app_base_url="", secret_key="change-me" * 5)
    assert validate_production_settings(bad) == []


def test_settings_refuses_start_and_unknown_env(monkeypatch):
    for k, v in {"APP_ENV": "production", "DATABASE_URL": "postgresql://u:scm_local_pw@h/d", "SECRET_KEY": "x" * 40}.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ValidationError, match="COOKIE_SECURE"):
        Settings(_env_file=None)
    monkeypatch.setenv("APP_ENV", "staging")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize("env,host,db,allow,blocked", [
    ("development", "localhost", "scm", "", False),
    ("development", "127.0.0.1", "scm", "", False),
    ("development", "db", "scm", "", False),
    ("production", "localhost", "scm", "", True),  # 운영 모드
    ("development", "localhost", "scm_test", "", True),  # 테스트 DB (기존 규칙)
    ("development", "localhost", None, "", True),  # DB 이름 없음
    ("development", "prod.example.com", "scm", "", True),  # 낯선 호스트
    ("development", "prod.example.com", "scm", "other.example.com", True),  # 허용 호스트가 다름
    ("development", "prod.example.com", "scm", "prod.example.com", False),  # 정확히 같음
    ("development", "prod.example.com", "scm_test", "prod.example.com", True),  # 예외여도 테스트 DB 는 막힘
    ("production", "prod.example.com", "scm", "prod.example.com", True),  # 예외여도 운영 모드는 막힘
])
def test_check_seed_allowed(env, host, db, allow, blocked):
    assert (check_seed_allowed(env, host, db, allow) is not None) == blocked
