"""아침 발주 추천 DM 테스트 (#197 PR 4). 슬랙에는 보내지 않는다: 가짜 클라이언트가 기록만 한다. 날짜는 TODAY 로 고정."""

import logging  # 사유 코드 로그 확인
from contextlib import nullcontext  # 테스트 세션을 닫지 않고 빌려주기
from datetime import UTC, datetime  # 연결 시각

import pytest  # 테스트 도구
from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답
from sqlalchemy import select, text, update  # 키 조회, 만료 시각 옮기기

from app import slack_digest as command  # 명령 진입점 (종료 코드)
from app.config import settings  # SLACK_*·APP_BASE_URL
from app.models import IdempotencyKey, SlackLink  # 멱등 키, 슬랙 연결
from app.services import slack_client, slack_digest  # 검사 대상
from tests.helpers import FakeSlackClient  # 가짜 슬랙
from tests.test_recommendations import (  # 추천 1개가 나오는 품목 (가용 50 ≤ 재주문점 70)
    TODAY,
    add_product,
    stock_50_sold_300,
)

TEAM = "T0TEAM"
T0 = datetime(2026, 11, 16, tzinfo=UTC)


class FailFor(FakeSlackClient):
    """특정 슬랙 사용자에게만 실패하는 가짜."""

    def __init__(self, bad: str):
        super().__init__()
        self.bad = bad

    def post_message(self, channel, text, thread_ts=None):
        if channel == self.bad:
            raise SlackApiError("x", {"ok": False, "error": "channel_not_found"})
        super().post_message(channel, text, thread_ts)


@pytest.fixture
def fake(monkeypatch):
    client = FakeSlackClient()
    monkeypatch.setattr(slack_client, "get_client", lambda: client)  # 외부 호출 0번
    return client


@pytest.fixture
def slack_on(monkeypatch, session, fake):
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "slack_team_id", TEAM)
    monkeypatch.setattr(settings, "app_base_url", "https://scm.example.com/")
    monkeypatch.setattr(slack_digest, "SessionLocal", lambda: nullcontext(session))  # 개발 DB 대신 테스트 세션
    monkeypatch.setattr(slack_digest, "ReadSessionLocal", lambda: nullcontext(session))


@pytest.fixture
def logs(caplog, monkeypatch):
    monkeypatch.setattr(slack_digest.log, "disabled", False)  # alembic fileConfig 가 꺼 둔 로거를 다시 켠다
    caplog.set_level(logging.INFO)
    return caplog


def link(session, world, key: str, slack_user: str, team: str = TEAM) -> None:
    user = world[key]
    session.add(SlackLink(company_id=user.company_id, user_id=user.id, slack_team_id=team, slack_user_id=slack_user, linked_at=T0))
    session.commit()


def run():
    return slack_digest.send_digests(TODAY)


def item(**over) -> dict:
    """웹 추천 API items 한 줄 모양 (메시지에 쓰는 칸만)."""
    base = {"product_name": "생수 500ml", "product_sku": "WTR-500", "unit": "개", "unit_factor": 1, "order_unit": "개",
            "recommended_order_units": 160, "recommended_arrival_quantity": 160, "available": 50, "draft": None,
            "color": None, "size": None, "spec": None}
    return base | over


# ----- 메시지 (순수 함수) -----

def test_message_box_draft_escape_and_link():
    msg = slack_digest.build_message([
        item(product_name="A<&>B", unit_factor=100, order_unit="BOX", recommended_order_units=3, recommended_arrival_quantity=300),
        item(product_sku="WIP-100", draft={"po_number": "PO-2026-0012"}),
    ], TODAY, "https://scm.example.com/")
    assert f"({TODAY.month}월 {TODAY.day}일)" in msg
    assert "1. A&lt;&amp;&gt;B (WTR-500) — 3 BOX(300개) 추천 · 지금 쓸 수 있는 재고 50개" in msg
    assert "— 160개 추천" in msg and "작성 중 발주서 PO-2026-0012에 있어요" in msg
    assert "\n2. 생수 500ml (WIP-100)" in msg  # 줄 번호가 이어진다
    assert msg.endswith("자세한 이유: https://scm.example.com/recommendations\n답장 예: 1번 3박스 (더 보려면 '도움말')")  # 링크 다음 마지막 줄이 답장 안내


def test_message_overflow_shows_rest():
    msg = slack_digest.build_message([item(product_sku=f"S{i}") for i in range(12)], TODAY, "https://scm.example.com")
    assert [line.split(".")[0] for line in msg.split("\n")[3:13]] == [str(n) for n in range(1, 11)]  # 1. ~ 10.
    assert "11." not in msg
    assert msg.endswith("외 2개는 웹에서 확인해 주세요: https://scm.example.com/recommendations\n답장 예: 1번 3박스 (더 보려면 '도움말')")


@pytest.mark.parametrize("base", ["", "http://localhost:3000", "javascript:alert(1)"])
def test_message_without_https_has_no_link(base):
    msg = slack_digest.build_message([item()], TODAY, base)
    assert "http" not in msg.split("\n")[-2] and msg.endswith("웹의 '발주 추천' 화면에서 볼 수 있어요.\n답장 예: 1번 3박스 (더 보려면 '도움말')")
    over = slack_digest.build_message([item(product_sku=f"S{i}") for i in range(11)], TODAY, base)
    assert over.endswith("외 1개는 웹의 '발주 추천' 화면에서 확인해 주세요.\n답장 예: 1번 3박스 (더 보려면 '도움말')")


def test_message_shows_options_and_escapes_them():
    msg = slack_digest.build_message([
        item(product_name="기본 티셔츠", product_sku="TS-BK-M", color="검정", size="M"),
        item(product_name="기본 티셔츠", product_sku="TS-WH-M", color="흰색", size="M"),  # 이름이 같아도 옵션으로 구분
        item(product_name="물티슈", product_sku="WIP-1", spec="30<롤>&"),
        item(product_name="생수", product_sku="WTR-1"),  # 옵션 없음: 옵션 부분 생략
    ], TODAY, "https://scm.example.com/")
    assert "1. 기본 티셔츠 · 검정 / M (TS-BK-M) — " in msg and "2. 기본 티셔츠 · 흰색 / M (TS-WH-M) — " in msg
    assert "3. 물티슈 · 30&lt;롤&gt;&amp; (WIP-1) — " in msg and "<롤>" not in msg
    assert "4. 생수 (WTR-1) — " in msg and "·" not in msg.split("\n4. ")[1].split(" — ")[0]


# ----- 보내기 -----

def test_sends_to_each_linked_user_of_own_company_only(session, world, slack_on, fake):
    stock_50_sold_300(session, world, "A-REC")  # 회사 A 추천 1개
    stock_50_sold_300(session, world, "B-REC", key="b")  # 회사 B 추천 1개
    session.commit()
    link(session, world, "a_admin", "UA1")
    link(session, world, "a_staff", "UA2")  # 한 회사 여러 명 → 각자 한 통
    link(session, world, "b_staff", "UB1")
    assert run() == {"SENT": 3}
    sent = {channel: msg for channel, msg, _ in fake.sent}
    assert set(sent) == {"UA1", "UA2", "UB1"}  # 사용자 id 를 채널로
    assert "A-REC" in sent["UA1"] and "B-REC" not in sent["UA1"] and "A-REC" in sent["UA2"]
    assert "B-REC" in sent["UB1"] and "A-REC" not in sent["UB1"]  # 회사 격리
    assert all(thread is None for _, _, thread in fake.sent)


def test_no_items_no_links_and_excluded_users_get_nothing(session, world, slack_on, fake):
    add_product(session, world, "NO-HISTORY")  # 회사 A: 이력 없음 → 제외(데이터 부족)라 추천 0개
    stock_50_sold_300(session, world, "B-REC", key="b")  # 회사 B: 추천은 있지만 아래 이유로 아무도 못 받음
    session.commit()
    link(session, world, "a_staff", "UA1")  # 추천 0개 회사
    link(session, world, "b_admin", "UB1", team="TOTHER")  # 다른 워크스페이스
    world["b_staff"].is_active = False
    session.add(SlackLink(company_id=world["b_staff"].company_id, user_id=world["b_staff"].id, link_code_hash="h" * 64))  # 코드만 발급(대기)
    session.commit()
    assert run() == {"NO_ITEMS": 1}
    assert fake.sent == []


def test_disabled_sends_nothing(session, world, slack_on, fake, monkeypatch):
    stock_50_sold_300(session, world, "A-REC")
    link(session, world, "a_staff", "UA1")
    monkeypatch.setattr(settings, "slack_enabled", False)
    assert run() == {}
    assert fake.sent == []


def test_same_day_rerun_is_blocked_before_24h(session, world, slack_on, fake):
    stock_50_sold_300(session, world, "A-REC")
    link(session, world, "a_staff", "UA1")
    assert run() == {"SENT": 1}
    key = select(IdempotencyKey).where(IdempotencyKey.endpoint == "slack:digest")
    row = session.scalar(key)
    assert row.idempotency_key == f"{TODAY.isoformat()}:{world['a_staff'].id}"
    # 만료 판단은 DB now()(이 테스트 트랜잭션 안에서는 고정) 기준. 키를 23시간 59분 전에 잡은 것으로 옮긴다
    session.execute(update(IdempotencyKey).where(IdempotencyKey.id == row.id).values(created_at=text("now() - interval '23 hours 59 minutes'")))
    session.commit()
    assert run() == {"ALREADY_SENT": 1}  # 같은 날짜, 24시간 전 → 막힌다
    assert len(fake.sent) == 1
    # 24시간이 지나면 키가 지워진다. 서울 날짜가 키에 들어 있어 같은 날짜로 24시간 뒤에 실행되는 일은 실제로는 없다
    session.execute(update(IdempotencyKey).where(IdempotencyKey.id == row.id).values(created_at=text("now() - interval '24 hours 1 minute'")))
    session.commit()
    assert run() == {"SENT": 1}


def test_partial_failure_retries_only_failed_user(session, world, slack_on, monkeypatch, logs):
    stock_50_sold_300(session, world, "A-REC")
    link(session, world, "a_admin", "UA1")
    link(session, world, "a_staff", "UA2")
    failing = FailFor("UA1")
    monkeypatch.setattr(slack_client, "get_client", lambda: failing)
    assert run() == {"SEND_FAILED": 1, "SENT": 1}
    assert [c for c, _, _ in failing.sent] == ["UA2"]
    assert "error=channel_not_found" in logs.text
    ok = FakeSlackClient()
    monkeypatch.setattr(slack_client, "get_client", lambda: ok)
    assert run() == {"ALREADY_SENT": 1, "SENT": 1}  # 실패한 사람에게만 다시
    assert [c for c, _, _ in ok.sent] == ["UA1"]
    assert "UA1" not in logs.text and "UA2" not in logs.text and "A-REC" not in logs.text  # 슬랙 사용자 id·원문 없음


def test_unexpected_error_is_isolated(session, world, slack_on, monkeypatch):
    stock_50_sold_300(session, world, "A-REC")
    link(session, world, "a_staff", "UA1")
    monkeypatch.setattr(slack_client, "get_client", lambda: FakeSlackClient(fail=TimeoutError()))
    assert run() == {"SEND_FAILED": 1}
    assert session.scalar(select(IdempotencyKey).where(IdempotencyKey.endpoint == "slack:digest")) is None  # 키도 취소


def test_command_exit_code(monkeypatch):
    monkeypatch.setattr(command, "seoul_today", lambda: TODAY)
    monkeypatch.setattr(slack_digest, "send_digests", lambda day: {"SENT": 2})
    assert command.main() == 0
    monkeypatch.setattr(slack_digest, "send_digests", lambda day: {"SENT": 1, "SEND_FAILED": 1})
    assert command.main() == 1
