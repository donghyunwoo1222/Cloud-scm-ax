"""테스트 공통 도우미 (fixture 가 아닌 일반 값·함수)."""

from datetime import UTC, datetime  # 유예 종료 시각

PASSWORD = "test-password"  # conftest 의 world 사용자 공통 비밀번호 (테스트 전용)
GRACE_UNTIL = datetime(2100, 1, 1, tzinfo=UTC)  # world 관리자의 OTP 유예 종료 (#179). 아주 먼 미래라 기존 테스트는 코드 없이 로그인한다


class FakeSlackClient:
    """슬랙 대신 보낸 메시지를 기록하는 가짜 클라이언트 (#197). fail 에 예외를 넣으면 보낼 때마다 그 예외를 낸다."""

    def __init__(self, fail: Exception | None = None):
        self.sent: list[tuple[str, str, str | None]] = []  # (채널, 글, 스레드)
        self.blocks: list[list[dict]] = []  # 블록이 함께 간 메시지의 블록들 (sent 와 같은 순서, 블록 없는 메시지는 안 넣는다)
        self.updated: list[tuple[str, str, str, list[dict]]] = []  # (채널, ts, 글, 블록)
        self.ephemeral: list[tuple[str, str, str]] = []  # (채널, 보이는 사람, 글)
        self.fail = fail
        self.fail_update: Exception | None = None  # update_message 만 실패시킨다
        self.fail_ephemeral: Exception | None = None  # post_ephemeral 만 실패시킨다

    def post_message(self, channel: str, text: str, thread_ts: str | None = None, blocks: list[dict] | None = None) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((channel, text, thread_ts))
        if blocks is not None:
            self.blocks.append(blocks)

    def update_message(self, channel: str, ts: str, text: str, blocks: list[dict]) -> None:
        if self.fail_update is not None:
            raise self.fail_update
        self.updated.append((channel, ts, text, blocks))

    def post_ephemeral(self, channel: str, user: str, text: str) -> None:
        if self.fail_ephemeral is not None:
            raise self.fail_ephemeral
        self.ephemeral.append((channel, user, text))


def login_as(client, email: str = "staff@a.test") -> None:
    """이 이메일로 로그인해 클라이언트가 쿠키를 갖게 한다. 기본은 회사 A 담당자."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})  # 로그인 요청
    assert response.status_code == 200  # 실패하면 테스트 준비가 잘못된 것
