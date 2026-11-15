"""개발용 슬랙 Socket Mode 워커 (#197 PR 3b). 슬랙이 웹소켓으로 보내 주는 이벤트를 slack_events.handle_event 로 넘긴다.

실행(저장소 맨 위 폴더):  docker compose exec backend python -m app.slack_worker   (끄기: Ctrl+C)
공개 주소가 없는 개발 PC 용이다. 배포에서는 HTTP 경로(POST /slack/events)를 쓰므로 이 파일은 띄우지 않는다.
재연결: SocketModeClient 가 연결이 끊기면 스스로 다시 잇는다(auto_reconnect_enabled 기본 True). 직접 다시 잇는 코드는 없다.
로그: 사유 코드만 남긴다. 토큰·메시지 원문은 어디에도 찍지 않는다(예외도 종류 이름만).
"""

import logging  # 사유 코드 한 줄
import signal  # Ctrl+C(SIGINT)·SIGTERM 로 깨끗하게 끄기
import threading  # 끄라는 신호를 기다리는 깃발

from slack_sdk.socket_mode import SocketModeClient  # 슬랙 웹소켓 클라이언트 (자동 재연결 내장)
from slack_sdk.socket_mode.request import SocketModeRequest  # 슬랙이 보낸 요청 한 건
from slack_sdk.socket_mode.response import SocketModeResponse  # "받았음" 응답

from app.config import settings  # SLACK_* 설정
from app.services import slack_events, slack_link  # 이벤트 처리, 처리 시각

log = logging.getLogger(__name__)


def _ignored(reason: str) -> None:
    log.info("slack_worker outcome=IGNORED reason=%s", reason)


def on_request(client: SocketModeClient, req: SocketModeRequest) -> None:
    """먼저 "받았음"(ack)을 보낸다(슬랙은 3초 안에 답이 없으면 다시 보낸다). 그다음 events_api 만 처리한다. 예외는 밖으로 내지 않는다."""
    try:
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
    except Exception as exc:  # noqa: BLE001  ack 실패: 슬랙이 다시 보내고 handle_event 가 event_id 로 중복을 막는다
        log.warning("slack_worker outcome=ACK_FAILED error=%s", type(exc).__name__)
        return
    if req.type != "events_api":  # interactive(버튼)·slash_commands 등은 PR 5
        _ignored(f"TYPE_{req.type}")
        return
    try:
        slack_events.handle_event(req.payload, slack_link.now())
    except Exception as exc:  # noqa: BLE001  handle_event 는 원래 예외를 안 내지만, 워커는 무슨 일이 있어도 살아 있어야 한다
        log.warning("slack_worker outcome=HANDLER_ERROR error=%s", type(exc).__name__)


def disabled_reason() -> str | None:
    """연결하면 안 되는 이유 코드(없으면 None). 값 자체는 보지 않고 비었는지만 본다."""
    if not settings.slack_enabled:
        return "SLACK_DISABLED"
    if not settings.slack_team_id:
        return "NO_TEAM_ID"
    if not settings.slack_app_token.get_secret_value():
        return "NO_APP_TOKEN"
    if not settings.slack_bot_token.get_secret_value():
        return "NO_BOT_TOKEN"
    return None


def make_client() -> SocketModeClient:
    """앱 토큰(xapp-)으로 연결한다. 테스트는 이 함수를 가짜로 바꿔 끼운다."""
    return SocketModeClient(app_token=settings.slack_app_token.get_secret_value())


def main(stop: threading.Event | None = None) -> int:
    """꺼져 있으면 연결 없이 0. 켜져 있으면 연결하고 stop 이 켜질 때까지(없으면 Ctrl+C·SIGTERM) 기다린다."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)  # DEBUG 로그에 토큰이 섞일 수 있다
    reason = disabled_reason()
    if reason:
        log.info("slack_worker disabled reason=%s", reason)
        return 0
    if stop is None:  # 직접 실행: 신호가 오면 깃발을 켠다 (테스트는 stop 을 넘기므로 신호 처리기를 건드리지 않는다)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
    client = make_client()
    client.socket_mode_request_listeners.append(on_request)
    try:
        client.connect()
        log.info("slack_worker started")
        while not stop.wait(1):  # 1초마다 깨어나야 Windows 에서도 Ctrl+C 가 먹는다
            pass
    except Exception as exc:  # noqa: BLE001  첫 연결 실패(토큰 오류·네트워크). 이유 종류만 남긴다
        log.error("slack_worker outcome=CONNECT_FAILED error=%s", type(exc).__name__)
        return 1
    finally:
        client.close()
        log.info("slack_worker stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
