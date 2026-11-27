import logging  # DB 실패 로그를 확인한다
from contextlib import nullcontext  # 가짜 연결을 with 문에서 쓰게 한다
from unittest.mock import Mock  # DB 연결 실패를 재현한다

import pytest
from fastapi.testclient import TestClient  # 서버를 띄우지 않고 앱에 가짜 요청을 보내는 도구
from sqlalchemy import event  # 실제 엔진에 전달된 SQL을 기록한다
from sqlalchemy.exc import OperationalError  # DB 접속 또는 쿼리 실패

from app.api import health  # 상태 확인에서 쓰는 엔진을 바꿔 끼운다
from app.main import app  # 테스트할 앱

client = TestClient(app)  # 가짜 요청 보내는 클라이언트


def test_health_returns_ok():
    response = client.get("/api/v1/health")  # health 경로를 부른다
    assert response.status_code == 200  # 200(정상)이어야 한다
    assert response.json() == {"status": "ok"}  # 본문이 {"status": "ok"} 여야 한다


def test_healthz_does_not_connect_to_db(monkeypatch):
    connect = Mock(side_effect=AssertionError("DB를 호출하면 안 된다"))
    monkeypatch.setattr(health.engine, "connect", connect)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.content == b""
    connect.assert_not_called()


def test_healthz_db_runs_select_one(engine, monkeypatch):
    # 테스트 전용 PostgreSQL에 실제로 연결한다.
    monkeypatch.setattr(health, "engine", engine)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        response = client.get("/healthz/db")
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert response.status_code == 200
    assert response.content == b""
    assert statements == ["SELECT 1"]


@pytest.mark.parametrize("stage", ["connect", "execute"])
def test_healthz_db_failure_hides_details(stage, monkeypatch, caplog):
    fake_url = "postgresql+psycopg://demo:fake-password@db.example.invalid/test"
    detail = "fake-driver-error"
    failure = OperationalError("SELECT 1", None, RuntimeError(f"{detail} {fake_url}"))
    connection = Mock()
    connection.execute.side_effect = failure
    connect = Mock(return_value=nullcontext(connection))
    if stage == "connect":
        connect.side_effect = failure
    monkeypatch.setattr(health.engine, "connect", connect)
    monkeypatch.setattr(health.logger, "disabled", False)  # 테스트 DB를 준비한 Alembic이 끈 로거를 다시 켠다

    with caplog.at_level(logging.WARNING, logger=health.logger.name):
        response = client.get("/healthz/db")

    assert response.status_code == 503
    assert response.content == b""
    assert "Database health check failed" in caplog.text
    assert fake_url not in caplog.text
    assert detail not in caplog.text
