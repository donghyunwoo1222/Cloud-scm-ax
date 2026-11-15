"""슬랙으로 메시지를 보내는 얇은 클라이언트 (#197). 테스트는 get_client 를 가짜로 바꿔 끼워 외부 호출 없이 돌린다.

토큰은 SecretStr 로 들고 있다가 클라이언트를 만들 때 한 번만 꺼낸다. 로그·예외 문장에 토큰을 넣지 않는다.
"""

from slack_sdk import WebClient  # 슬랙 Web API (표준 urllib 기반, 추가 패키지 없음)

from app.config import settings  # SLACK_BOT_TOKEN

TIMEOUT_SECONDS = 5  # 슬랙이 느려도 뒤 작업 스레드를 오래 잡지 않게


class SlackClient:
    """chat.postMessage 하나만 쓴다."""

    def __init__(self, token: str):
        self._web = WebClient(token=token, timeout=TIMEOUT_SECONDS)

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> None:
        """channel(DM 이면 D… id)에 text 를 보낸다. thread_ts 가 있으면 그 스레드에 답한다. 실패하면 slack_sdk 예외."""
        self._web.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)  # None 인 값은 slack_sdk 가 빼고 보낸다


_client: SlackClient | None = None


def get_client() -> SlackClient:
    """처음 부를 때 한 번 만든다. 봇 토큰이 비어 있으면 ValueError (부르는 쪽이 SEND_FAILED 로 남긴다)."""
    global _client
    if _client is None:
        token = settings.slack_bot_token.get_secret_value()
        if not token:
            raise ValueError("SLACK_BOT_TOKEN is empty")
        _client = SlackClient(token)
    return _client
