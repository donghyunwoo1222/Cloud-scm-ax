import subprocess  # 앱 시작과 같은 import를 별도 프로세스에서 실행한다
import sys  # 현재 Python 실행 파일을 사용한다

import pytest
from pydantic import ValidationError

from app.config import Settings, settings

POOL_ENV = ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_RECYCLE")


def test_db_pool_defaults(monkeypatch):
    for name in POOL_ENV:  # 로컬 환경과 .env에 풀 값이 있어도 기본값을 확인한다
        monkeypatch.delenv(name, raising=False)
    config = Settings(_env_file=None, database_url=settings.database_url, secret_key=settings.secret_key,
                      app_env="development")

    assert (config.db_pool_size, config.db_max_overflow, config.db_pool_recycle) == (5, 5, 1800)


def test_db_pool_environment_reaches_engine(monkeypatch):
    # 앱 시작과 같은 import를 독립 프로세스에서 실행해 기존 엔진에 영향을 주지 않는다.
    for name, value in zip(POOL_ENV, ("2", "0", "900"), strict=True):
        monkeypatch.setenv(name, value)

    subprocess.run(
        [sys.executable, "-c", """
from app.db import engine
assert engine.pool.size() == 2
assert engine.pool._max_overflow == 0
assert engine.pool._recycle == 900
assert engine.pool._pre_ping is True
"""],
        check=True,
    )


@pytest.mark.parametrize("name", POOL_ENV)
@pytest.mark.parametrize("value", ["-1", "abc", "1.5"])
def test_db_pool_rejects_invalid_values(name, value, monkeypatch):
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError, match=name.lower()):
        Settings(database_url=settings.database_url, secret_key=settings.secret_key, app_env="development")


def test_db_pool_rejects_unlimited_size(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "0")

    with pytest.raises(ValidationError, match="db_pool_size"):
        Settings(database_url=settings.database_url, secret_key=settings.secret_key, app_env="development")
