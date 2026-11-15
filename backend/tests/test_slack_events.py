"""슬랙 받는 문 테스트 (#197 PR 3a). 슬랙에는 연결하지 않는다: 서명은 테스트 키로 직접 만들고, 답장은 가짜 클라이언트가 기록한다."""

import hashlib  # 서명 계산
import hmac  # 서명 계산
import json  # 본문 만들기
import logging  # 사유 코드 로그 확인
import time  # 서명 시각
from contextlib import nullcontext  # 테스트 세션을 닫지 않고 빌려주기
from datetime import UTC, datetime  # 고정 시각

import pytest  # 테스트 도구
from pydantic import SecretStr  # 설정의 비밀 값 모양
from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답
from sqlalchemy import select  # 행 조회

from app.config import settings  # SLACK_* 설정
from app.models import IdempotencyKey, SlackLink  # 멱등 키 표, 슬랙 연결 표
from app.services import chat_order, slack_client, slack_events, slack_link  # 검사 대상
from tests.helpers import FakeSlackClient, login_as  # 가짜 슬랙, 공통 로그인

URL = "/api/v1/slack/events"
T0 = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)  # 고정 처리 시각 (연결 코드 만료 계산용)
TEAM = "T0TEAM"
SECRET = "test-signing-secret"  # 테스트 전용 서명 키
BOT = "UBOT"  # 이 설치의 봇 사용자 id


@pytest.fixture(autouse=True)
def clean_memory():
    slack_link.reset()  # 연결 실패 기록
    slack_events.reset()  # 최근 event_id 기록
    yield


@pytest.fixture
def fake(monkeypatch):
    client = FakeSlackClient()
    monkeypatch.setattr(slack_client, "get_client", lambda: client)  # 외부 호출 0번
    return client


@pytest.fixture
def slack_on(monkeypatch, session, fake):
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "slack_team_id", TEAM)
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SECRET))
    monkeypatch.setattr(slack_link, "now", lambda: T0)
    monkeypatch.setattr(slack_events, "SessionLocal", lambda: nullcontext(session))  # 개발 DB 대신 테스트 세션 (닫지 않는다)


@pytest.fixture
def outcomes(caplog, monkeypatch):
    """slack_events 사유 코드 목록을 돌려주는 함수."""
    monkeypatch.setattr(slack_events.log, "disabled", False)  # alembic fileConfig 가 꺼 둔 로거를 다시 켠다 (test_slack_link 와 같다)
    caplog.set_level(logging.INFO)
    return lambda: [r.args[0] for r in caplog.records if r.name == "app.services.slack_events"]


def signed(body: bytes, ts: int | None = None, secret: str = SECRET) -> dict:
    stamp = str(int(time.time()) if ts is None else ts)
    sig = "v0=" + hmac.new(secret.encode(), f"v0:{stamp}:".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Slack-Request-Timestamp": stamp, "X-Slack-Signature": sig, "Content-Type": "application/json"}


def dm(text: str, event_id: str = "Ev1", user: str = "U1", team: str = TEAM, **event) -> dict:
    """사람이 봇에게 보낸 DM 한 통의 봉투 (message.im 모양)."""
    return {
        "type": "event_callback", "team_id": team, "api_app_id": "A1", "event_id": event_id, "event_time": 1,
        "authorizations": [{"team_id": team, "user_id": BOT, "is_bot": True}],
        "event": {"type": "message", "channel": "D1", "user": user, "text": text, "ts": "1.1",
                  "event_ts": "1.1", "channel_type": "im", **event},
    }


def post(client, envelope: dict, **kw):
    body = json.dumps(envelope).encode()
    return client.post(URL, content=body, headers=signed(body, **kw))


def issue_code(session, world, key="a_staff") -> str:
    code, _ = slack_link.issue_code(session, world[key], T0)
    return code


def link(client, session, world, user="U1", key="a_staff") -> None:
    assert post(client, dm(f"연결 {issue_code(session, world, key)}", event_id="EvLink", user=user)).status_code == 200


# ----- 문 (서명·스위치·url_verification) -----

def test_disabled_is_404(client, world, fake):
    assert post(client, dm("안녕")).status_code == 404  # 기본값: 꺼짐
    assert fake.sent == []


def test_missing_signing_secret_is_404(client, world, slack_on, monkeypatch):
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(""))
    assert post(client, dm("안녕")).status_code == 404  # 빈 키로는 아무것도 통과시키지 않는다


def test_url_verification(client, slack_on):
    response = post(client, {"type": "url_verification", "token": "x", "challenge": "abc123"})
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc123"}


@pytest.mark.parametrize("kw", [{"secret": "wrong-secret"}, {"ts": int(time.time()) - 400}])  # 위조, 6분 넘은 시각
def test_bad_signature_is_401(client, world, slack_on, fake, outcomes, kw):
    response = post(client, dm("안녕"), **kw)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SLACK_BAD_SIGNATURE"
    assert fake.sent == []


def test_tampered_body_is_401(client, world, slack_on, fake):
    body = json.dumps(dm("안녕")).encode()
    headers = signed(body)
    assert client.post(URL, content=body.replace(b'"Ev1"', b'"Ev2"'), headers=headers).status_code == 401
    assert client.post(URL, content=body).status_code == 401  # 서명 헤더 없음
    assert fake.sent == []


# ----- 연결 -----

def test_link_success(client, session, world, slack_on, fake, outcomes):
    code = issue_code(session, world)
    assert post(client, dm(f"연결 {code}")).status_code == 200
    assert fake.sent == [("D1", slack_events.LINKED, None)]
    row = session.scalar(select(SlackLink).where(SlackLink.user_id == world["a_staff"].id))
    assert (row.slack_team_id, row.slack_user_id, row.company_id) == (TEAM, "U1", world["a_company"].id)  # 회사는 코드 행에서
    assert outcomes() == ["LINK_OK"]


def test_link_wrong_code(client, world, slack_on, fake, outcomes):
    assert post(client, dm("연결 000000")).status_code == 200
    assert fake.sent == [("D1", slack_link.FAIL_MESSAGE, None)]
    assert outcomes() == ["LINK_FAIL"]


def test_retried_wrong_code_counts_once(client, world, slack_on, fake, outcomes):
    """재전송된 같은 이벤트는 실패를 두 번 세지 않는다 (잠금이 빨리 걸리지 않게)."""
    post(client, dm("연결 000000", event_id="EvX"))
    post(client, dm("연결 000000", event_id="EvX"))
    assert len(fake.sent) == 1
    assert slack_link._failures[(TEAM, "U1")][0] == 1
    assert outcomes() == ["LINK_FAIL", "DUPLICATE"]


def test_locked_after_five_failures(client, session, world, slack_on, fake):
    for i in range(5):
        post(client, dm("연결 000000", event_id=f"EvF{i}"))
    post(client, dm(f"연결 {issue_code(session, world)}", event_id="EvOk"))  # 맞는 코드여도 잠김
    assert fake.sent[-1] == ("D1", slack_link.FAIL_MESSAGE, None)
    assert session.scalar(select(SlackLink.linked_at).where(SlackLink.user_id == world["a_staff"].id)) is None


def test_retry_after_link_does_not_send_failure(client, session, world, slack_on, fake, outcomes):
    """연결에 성공한 이벤트가 다시 와도 '코드가 맞지 않거나' 문구가 가지 않는다."""
    envelope = dm(f"연결 {issue_code(session, world)}", event_id="EvL")
    post(client, envelope)
    post(client, envelope)
    assert fake.sent == [("D1", slack_events.LINKED, None)]
    assert outcomes() == ["LINK_OK", "DUPLICATE"]


# ----- 연결 후·연결 전의 다른 메시지 -----

def test_unlinked_other_message(client, world, slack_on, fake):
    post(client, dm("A 품목 300개"))
    assert fake.sent == [("D1", slack_events.NOT_LINKED, None)]


def test_linked_other_message_and_duplicate(client, session, world, slack_on, fake, outcomes):
    link(client, session, world)
    post(client, dm("A 품목 300개", event_id="Ev2"))
    post(client, dm("A 품목 300개", event_id="Ev2"))  # 재전송
    assert fake.sent[1:] == [("D1", chat_order.MSG_NO_ITEMS, None)]  # 연결된 사용자의 글은 채팅 발주로 간다(추천 품목이 없는 회사)
    keys = session.scalars(select(IdempotencyKey).where(IdempotencyKey.idempotency_key == "Ev2")).all()
    assert [(k.company_id, k.endpoint) for k in keys] == [(world["a_company"].id, "slack:event")]  # 회사는 연결 행에서
    assert outcomes()[-2:] == ["ORDER_NO_PROPOSAL", "DUPLICATE"]


def test_linked_user_link_message(client, session, world, slack_on, fake):
    link(client, session, world)
    post(client, dm("연결 123456", event_id="Ev3"))
    assert fake.sent[-1] == ("D1", slack_events.ALREADY_LINKED, None)


def test_same_event_id_in_two_companies_is_separate(client, session, world, slack_on, fake):
    """event_id 키는 회사별이다. 다른 회사의 같은 키가 이 회사 처리를 막지 않는다."""
    link(client, session, world, user="U1", key="a_staff")
    slack_events.reset()
    link(client, session, world, user="U2", key="b_staff")
    post(client, dm("안녕", event_id="EvSame", user="U1"))
    slack_events.reset()
    post(client, dm("안녕", event_id="EvSame", user="U2"))
    assert [s[1] for s in fake.sent[-2:]] == [chat_order.MSG_NO_ITEMS, chat_order.MSG_NO_ITEMS]


def test_reply_in_thread(client, world, slack_on, fake):
    post(client, dm("안녕", thread_ts="9.9"))
    assert fake.sent == [("D1", slack_events.NOT_LINKED, "9.9")]


# ----- 무시하는 이벤트 -----

@pytest.mark.parametrize("extra", [
    {"bot_id": "B1"},  # 봇 메시지
    {"subtype": "message_changed"},  # 수정
    {"user": BOT},  # 봇 자신
    {"channel_type": "channel"},  # DM 이 아님
    {"type": "app_mention"},
])
def test_ignored_events(client, world, slack_on, fake, outcomes, extra):
    post(client, dm("연결 000000", **extra))
    assert fake.sent == []
    assert outcomes() == ["IGNORED"]
    assert slack_link._failures == {}  # 실패로 세지도 않는다


def test_other_team_ignored(client, world, slack_on, fake, outcomes):
    post(client, dm("연결 000000", team="T0OTHER"))
    assert fake.sent == []
    assert outcomes() == ["WRONG_TEAM"]


# ----- 실패해도 웹은 정상 -----

@pytest.mark.parametrize("error", [ConnectionError("down"), SlackApiError("x", {"ok": False, "error": "channel_not_found"})])
def test_slack_failure_does_not_break_web(client, world, slack_on, fake, outcomes, error, caplog):
    fake.fail = error
    assert post(client, dm("안녕")).status_code == 200
    assert outcomes() == ["NOT_LINKED", "SEND_FAILED"]
    assert client.get("/api/v1/health").status_code == 200
    login_as(client)  # 웹 로그인도 그대로


def test_db_failure_is_contained_and_retry_works(client, session, world, slack_on, fake, outcomes, monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(slack_events, "SessionLocal", broken)
    assert post(client, dm("연결 000000", event_id="EvDb")).status_code == 200
    assert outcomes() == ["ERROR"]
    monkeypatch.setattr(slack_events, "SessionLocal", lambda: nullcontext(session))
    post(client, dm("연결 000000", event_id="EvDb"))  # 재전송은 다시 처리된다
    assert fake.sent == [("D1", slack_link.FAIL_MESSAGE, None)]


def test_logs_have_no_text_code_or_secret(client, session, world, slack_on, fake, caplog, monkeypatch):
    monkeypatch.setattr(slack_events.log, "disabled", False)
    monkeypatch.setattr(settings, "slack_bot_token", SecretStr("xoxb-secret-token"))
    caplog.set_level(logging.DEBUG)
    code = issue_code(session, world)
    post(client, dm(f"연결 {code}"))
    post(client, dm("비밀 메모 내용", event_id="Ev9"))
    for secret in (code, "비밀 메모", "xoxb-secret-token", SECRET, "U1"):
        assert secret not in caplog.text


# ----- 메모리 목록 -----

def test_seen_memory_expires_and_is_capped():
    assert slack_events._remember("Ev1", T0)
    assert not slack_events._remember("Ev1", T0)
    assert slack_events._remember("Ev1", T0.replace(minute=11))  # 10분 지나면 잊는다
    for i in range(slack_events.SEEN_MAX + 5):
        slack_events._remember(f"E{i}", T0.replace(minute=20))
    assert len(slack_events._seen) == slack_events.SEEN_MAX
    assert not slack_events._was_seen("E0", T0.replace(minute=20))  # 가장 오래된 것부터 지운다
