"""개발용 Socket Mode 워커 테스트 (#197 PR 3b). 슬랙에는 연결하지 않는다: 가짜 클라이언트·가짜 요청만 쓴다."""

import logging  # 로그 확인
import threading  # 끄는 깃발

import pytest  # 테스트 도구
from pydantic import SecretStr  # 설정의 비밀 값 모양
from slack_sdk.socket_mode.request import SocketModeRequest  # 슬랙 요청 모양

from app import slack_worker  # 검사 대상
from app.config import settings  # SLACK_* 설정

APP_TOKEN = "xapp-secret-app-token"  # 로그에 나오면 안 되는 값
BOT_TOKEN = "xoxb-secret-bot-token"
MESSAGE = "연결 123456"  # 로그에 나오면 안 되는 메시지 원문


class FakeSocketClient:
    """보낸 ack·연결·종료를 순서대로 기록하는 가짜. calls 는 공유 기록장."""

    def __init__(self, calls: list):
        self.calls = calls
        self.socket_mode_request_listeners: list = []

    def send_socket_mode_response(self, response) -> None:
        self.calls.append(("ack", response.envelope_id))

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))


@pytest.fixture
def calls(monkeypatch):
    """handle_event 호출과 ack 를 한 목록에 순서대로 모은다 (외부 호출 0번)."""
    record: list = []
    monkeypatch.setattr(slack_worker.slack_events, "handle_event", lambda env, at: record.append(("handle", env["event_id"])))
    return record


@pytest.fixture
def logs(caplog, monkeypatch):
    monkeypatch.setattr(slack_worker.log, "disabled", False)  # alembic fileConfig 가 꺼 둔 로거를 다시 켠다
    caplog.set_level(logging.INFO)
    return lambda: "\n".join(r.getMessage() for r in caplog.records)


def req(kind: str = "events_api") -> SocketModeRequest:
    return SocketModeRequest(type=kind, envelope_id="env-1", payload={"event_id": "Ev1", "event": {"text": MESSAGE}})


def configure(monkeypatch, enabled=True, team="T0TEAM", app=APP_TOKEN, bot=BOT_TOKEN) -> None:
    monkeypatch.setattr(settings, "slack_enabled", enabled)
    monkeypatch.setattr(settings, "slack_team_id", team)
    monkeypatch.setattr(settings, "slack_app_token", SecretStr(app))
    monkeypatch.setattr(settings, "slack_bot_token", SecretStr(bot))


def test_ack_comes_before_handle(calls):
    slack_worker.on_request(FakeSocketClient(calls), req())
    assert calls == [("ack", "env-1"), ("handle", "Ev1")]


@pytest.mark.parametrize("kind", ["interactive", "slash_commands"])
def test_other_types_only_ack(calls, logs, kind):
    slack_worker.on_request(FakeSocketClient(calls), req(kind))
    assert calls == [("ack", "env-1")]  # handle_event 는 부르지 않는다
    assert f"reason=TYPE_{kind}" in logs()


def test_handler_error_does_not_escape(monkeypatch, calls, logs):
    def boom(env, at):
        raise RuntimeError(MESSAGE)  # 예외 문장에 원문이 있어도 로그에는 종류만

    monkeypatch.setattr(slack_worker.slack_events, "handle_event", boom)
    slack_worker.on_request(FakeSocketClient(calls), req())  # 예외가 나오면 여기서 실패
    assert "HANDLER_ERROR error=RuntimeError" in logs()
    assert MESSAGE not in logs()


def test_ack_failure_skips_handle(calls, logs):
    class BadAck(FakeSocketClient):
        def send_socket_mode_response(self, response) -> None:
            raise OSError("closed")

    slack_worker.on_request(BadAck(calls), req())
    assert calls == []  # 슬랙이 다시 보내므로 처리는 그때
    assert "ACK_FAILED error=OSError" in logs()


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [({"enabled": False}, "SLACK_DISABLED"), ({"team": ""}, "NO_TEAM_ID"), ({"app": ""}, "NO_APP_TOKEN"), ({"bot": ""}, "NO_BOT_TOKEN")],
)
def test_disabled_returns_zero_without_connecting(monkeypatch, calls, logs, kwargs, code):
    configure(monkeypatch, **kwargs)
    monkeypatch.setattr(slack_worker, "make_client", lambda: calls.append(("made",)))  # 만들어지면 실패
    assert slack_worker.main() == 0
    assert calls == []
    assert f"slack_worker disabled reason={code}" in logs()


def test_runs_and_closes_on_stop(monkeypatch, calls, logs):
    configure(monkeypatch)
    fake = FakeSocketClient(calls)
    monkeypatch.setattr(slack_worker, "make_client", lambda: fake)
    stop = threading.Event()
    stop.set()  # 시작하자마자 끄라는 신호
    assert slack_worker.main(stop) == 0
    assert calls == [("connect",), ("close",)]
    assert fake.socket_mode_request_listeners == [slack_worker.on_request]
    assert "slack_worker started" in logs()
    assert APP_TOKEN not in logs() and BOT_TOKEN not in logs()  # 토큰은 로그에 없다


def test_connect_failure_returns_one_and_closes(monkeypatch, calls, logs):
    configure(monkeypatch)

    class BadConnect(FakeSocketClient):
        def connect(self) -> None:
            raise ConnectionError(APP_TOKEN)  # 예외 문장에 토큰이 있어도 로그에는 종류만

    monkeypatch.setattr(slack_worker, "make_client", lambda: BadConnect(calls))
    assert slack_worker.main(threading.Event()) == 1
    assert calls == [("close",)]
    assert "CONNECT_FAILED error=ConnectionError" in logs()
    assert APP_TOKEN not in logs()
