"""슬랙 채팅 발주 어댑터 테스트 (#197 PR 5b): DM 답장 → 요약 + 버튼 → 버튼 → 초안. 가짜 슬랙·가짜 LLM, 외부 호출 0번.

품목: 번호 1 = BOX(1박스=100개, 추천 2박스), 번호 2 = ONE(낱개, 추천 160개). 슬랙 사용자: UA 담당자·UB 관리자(회사 A), UC 담당자(회사 B).
시각은 NOW(서울 오늘 새벽 3시)로 고정한다. 추천 계산이 실제 오늘(TODAY)을 쓰므로 같은 날로 맞춘다.
"""

# ruff: noqa: F811  (빌려 온 fixture 이름 ai 를 테스트 인자로 다시 쓰는 것은 pytest 의 정상 방식)
import itertools  # 이벤트 id 만들기
import json  # 버튼 본문
import logging  # 로그에 비밀이 없는지
import re  # 이스케이프가 끊기지 않았는지
from contextlib import nullcontext  # 테스트 세션을 닫지 않고 빌려주기
from datetime import datetime, time, timedelta  # 고정 시각
from urllib.parse import quote  # payload= 폼 글자

import pytest  # 테스트 도구
from pydantic import SecretStr  # 설정의 비밀 값 모양
from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답
from sqlalchemy import select  # 행 조회

from app.clock import SEOUL  # 서울 시간대
from app.config import settings  # SLACK_*·APP_BASE_URL
from app.models import PurchaseOrder, SlackLink  # 발주서, 슬랙 연결
from app.services import chat_order as co  # 문구·토큰
from app.services import slack_client, slack_events, slack_link  # 검사 대상
from tests.helpers import FakeSlackClient  # 가짜 슬랙
from tests.test_chat_order import L, ai  # noqa: F401  가짜 LLM(ai 는 fixture, 다른 테스트 파일에서 빌려 쓴다)
from tests.test_recommendations import TODAY, stock_50_sold_300  # 추천 대상 품목
from tests.test_slack_events import SECRET, TEAM, dm, signed  # 서명·DM 봉투 만들기

EVENTS = "/api/v1/slack/events"
INTERACTIONS = "/api/v1/slack/interactions"
NOW = datetime.combine(TODAY, time(3, 0), tzinfo=SEOUL)
STAFF, ADMIN, OTHER_CO = "U0AAAA1", "U0BBBB2", "U0CCCC3"  # 슬랙 사용자 id (로그에 나오면 안 되는 값)
_ids = itertools.count(1)


@pytest.fixture(autouse=True)
def clean_memory():
    slack_link.reset()
    slack_events.reset()
    yield


@pytest.fixture
def fake(monkeypatch):
    client = FakeSlackClient()
    monkeypatch.setattr(slack_client, "get_client", lambda: client)
    return client


@pytest.fixture
def slack_on(monkeypatch, session, fake):
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "slack_team_id", TEAM)
    monkeypatch.setattr(settings, "slack_signing_secret", SecretStr(SECRET))
    monkeypatch.setattr(settings, "app_base_url", "https://scm.example.com/")
    monkeypatch.setattr(slack_link, "now", lambda: NOW)
    monkeypatch.setattr(slack_events, "SessionLocal", lambda: nullcontext(session))


@pytest.fixture
def shop(session, world, slack_on):
    stock_50_sold_300(session, world, "ONE")
    stock_50_sold_300(session, world, "BOX", units_per_box=100, box_unit_cost=90_000, order_unit="박스")
    for key, slack in (("a_staff", STAFF), ("a_admin", ADMIN), ("b_staff", OTHER_CO)):
        user = world[key]
        session.add(SlackLink(company_id=user.company_id, user_id=user.id, slack_team_id=TEAM, slack_user_id=slack, linked_at=NOW))
    session.commit()


@pytest.fixture
def logs(caplog, monkeypatch):
    for module in (slack_events, co):
        monkeypatch.setattr(module.log, "disabled", False)  # alembic fileConfig 가 꺼 둔 로거를 다시 켠다
    caplog.set_level(logging.DEBUG)
    return lambda: caplog.text


def send(client, text, user=STAFF, team=TEAM, event_id=None):
    envelope = dm(text, event_id=event_id or f"Ev{next(_ids)}", user=user, team=team)
    body = json.dumps(envelope).encode()
    return client.post(EVENTS, content=body, headers=signed(body))


def propose_token(client, fake, ai, *lines, user=STAFF, text="1번 2박스"):
    """DM 을 보내 [확인][취소] 버튼의 토큰을 돌려준다."""
    ai.say(*lines)
    assert send(client, text, user=user).status_code == 200
    return fake.blocks[-1][-1]["elements"][0]["value"]  # 버튼 블록은 늘 마지막


def click(token, action=slack_events.CONFIRM_ID, user=STAFF, team=TEAM, channel="D1", ts="1700.01"):
    """block_actions payload (docs.slack.dev 의 키 이름 그대로)."""
    return {"type": "block_actions", "user": {"id": user, "team_id": team}, "team": {"id": team}, "channel": {"id": channel},
            "container": {"type": "message", "message_ts": ts, "channel_id": channel},
            "actions": [{"type": "button", "action_id": action, "value": token}], "response_url": "https://hooks.slack.test/x"}


def orders(session, world, key="a"):
    return list(session.scalars(select(PurchaseOrder).where(PurchaseOrder.company_id == world[f"{key}_company"].id)))


# ----- DM 답장 → 요약 + 버튼 -----

def test_reply_gets_summary_and_two_buttons(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1), L(2, 50, "base"))
    channel, text, _ = fake.sent[-1]
    assert channel == "D1" and "이대로 발주 초안을 만들까요?" in text and "(아직 만들지 않았어요)" in text
    section, actions = fake.blocks[-1]
    assert section["type"] == "section" and actions["type"] == "actions"
    confirm, cancel = actions["elements"]
    assert (confirm["action_id"], cancel["action_id"]) == (slack_events.CONFIRM_ID, slack_events.CANCEL_ID)
    assert confirm["value"] == cancel["value"] == token and "." in token  # 값은 토큰 하나뿐
    assert orders(session, world) == []  # 요약만, 아직 아무것도 만들지 않았다


def test_summary_escapes_special_characters(client, session, world, shop, ai, fake):
    from app.models import Product

    session.scalar(select(Product).where(Product.sku == "ONE")).name = "A<&>B"
    session.commit()
    propose_token(client, fake, ai, L(2))
    assert "A&lt;&amp;&gt;B" in fake.sent[-1][1] and "A<&>B" not in fake.sent[-1][1]


def test_help_and_cancel_words_are_answered_by_server(client, world, shop, ai, fake):
    send(client, "도움말")
    send(client, " 취소 ")
    assert [s[1] for s in fake.sent] == [slack_events.HELP, slack_events.CANCEL_IDLE]
    assert ai.calls == [] and fake.blocks == []  # LLM 을 부르지 않고 버튼도 없다


def test_unlinked_user_gets_notice_and_no_llm(client, world, shop, ai, fake):
    send(client, "1번 3박스", user="U0NOBODY")
    assert fake.sent == [("D1", slack_events.NOT_LINKED, None)]
    assert ai.calls == []


def test_other_workspace_is_ignored(client, world, shop, ai, fake, logs):
    send(client, "1번 3박스", team="T0OTHER")
    assert fake.sent == [] and ai.calls == []
    assert "outcome=WRONG_TEAM" in logs()


def test_slack_disabled_does_nothing(client, session, world, shop, ai, fake, monkeypatch):
    monkeypatch.setattr(settings, "slack_enabled", False)
    assert send(client, "1번 3박스").status_code == 404
    slack_events.handle_action(click("x.y"), NOW)  # 버튼도 마찬가지
    assert fake.sent == [] and fake.updated == [] and fake.ephemeral == [] and ai.calls == []


def test_unusable_reply_has_no_buttons(client, world, shop, ai, fake):
    ai.say()  # 알아듣지 못함
    send(client, "아무 말")
    assert fake.sent[-1][1].startswith(co.MSG_NO_LINES) and fake.blocks == []


# ----- 사람별 제한 -----

def test_rate_limit_per_person(client, world, shop, ai, fake, logs, monkeypatch):
    ai.say(L(1))
    for _ in range(5):
        send(client, "1번 2박스")  # 같은 사람이 연달아 5번
    texts = [s[1] for s in fake.sent]
    assert len(ai.calls) == slack_events.RATE_PER_MINUTE == 3  # 4·5번째는 LLM 까지 안 간다
    assert texts.count(slack_events.RATE_LIMITED) == 2
    assert "slack_order action=PROPOSE outcome=RATE_LIMITED" in logs()
    send(client, "1번 2박스", user=ADMIN)  # 다른 사람은 따로 센다
    assert len(ai.calls) == 4
    monkeypatch.setattr(slack_link, "now", lambda: NOW + timedelta(seconds=61))  # 1분 뒤에는 다시 된다
    send(client, "1번 2박스")
    assert len(ai.calls) == 5


def test_help_does_not_count_toward_limit(client, world, shop, ai, fake):
    for _ in range(5):
        send(client, "도움말")
    ai.say(L(1))
    send(client, "1번 2박스")
    assert len(ai.calls) == 1 and fake.sent[-1][1] != slack_events.RATE_LIMITED


# ----- 확인 버튼 -----

def test_confirm_creates_draft_and_replaces_buttons(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token), NOW)
    made = orders(session, world)
    assert len(made) == 1 and made[0].status == "DRAFT" and made[0].created_by == world["a_staff"].id  # 누른 사람
    channel, ts, text, blocks = fake.updated[0]
    assert (channel, ts) == ("D1", "1700.01")
    assert made[0].po_number in text and "승인과 발주는 웹에서 해 주세요." in text
    assert text.endswith("웹에서 보기: https://scm.example.com/purchase-orders")
    assert [b["type"] for b in blocks] == ["section"]  # 버튼(actions)이 없다
    assert fake.ephemeral == []


@pytest.mark.parametrize("base", ["", "http://localhost:3000", "javascript:alert(1)"])
def test_result_link_only_for_https(client, session, world, shop, ai, fake, monkeypatch, base):
    monkeypatch.setattr(settings, "app_base_url", base)
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token), NOW)
    assert "http" not in fake.updated[0][2] and "웹에서 보기" not in fake.updated[0][2]


def test_result_does_not_repeat_user_text(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1), text="비밀 메모 <b>안녕</b>")
    slack_events.handle_action(click(token), NOW)
    assert "비밀 메모" not in fake.updated[0][2] and "안녕" not in fake.updated[0][2]


def test_double_click_is_safe(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token), NOW)
    slack_events.handle_action(click(token), NOW)  # 두 번째 클릭
    assert len(orders(session, world)) == 1  # 서버의 nonce 가 막는다
    assert len(fake.updated) == 1  # 진짜 결과 문구를 덮어쓰지 않는다
    assert fake.ephemeral == [("D1", STAFF, co.MSG_DONE)]


def test_other_person_clicking_gets_private_notice(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token, user=ADMIN), NOW)  # 관리자가 담당자의 요청 버튼을 누름
    assert fake.ephemeral == [("D1", ADMIN, co.MSG_WRONG_USER)]  # 누른 사람에게만
    assert fake.updated == [] and orders(session, world) == []  # 원래 메시지는 그대로
    slack_events.handle_action(click(token), NOW)  # 원래 요청자는 여전히 확인할 수 있다
    assert len(orders(session, world)) == 1


def test_company_isolation_on_buttons(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token, user=OTHER_CO), NOW)  # 회사 B 사용자가 회사 A 토큰을 누름
    assert fake.ephemeral == [("D1", OTHER_CO, co.MSG_WRONG_USER)]
    assert orders(session, world, "a") == [] and orders(session, world, "b") == []


def test_other_company_user_sees_only_own_items(client, world, shop, ai, fake):
    send(client, "전부", user=OTHER_CO)  # 회사 B 에는 추천 품목이 없다
    assert fake.sent[-1][1] == co.MSG_NO_ITEMS and ai.calls == []


def test_expired_confirm(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token), NOW + timedelta(minutes=co.CONFIRM_MINUTES + 1))
    assert fake.updated[0][2] == co.MSG_EXPIRED and orders(session, world) == []


@pytest.mark.parametrize("bad", ["x.y", "abc", "e30.0000"])
def test_forged_token(client, session, world, shop, ai, fake, bad):
    slack_events.handle_action(click(bad), NOW)
    assert fake.updated[0][2] == co.MSG_INVALID and orders(session, world) == []


def test_tampered_token(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    body, sig = token.split(".")
    slack_events.handle_action(click(f"{body}.{'0' * len(sig)}"), NOW)
    assert fake.updated[0][2] == co.MSG_INVALID and orders(session, world) == []


def test_unlinked_clicker(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token, user="U0NOBODY"), NOW)
    assert fake.ephemeral == [("D1", "U0NOBODY", co.MSG_NOT_LINKED)] and orders(session, world) == []


# ----- 취소 버튼 -----

def test_cancel_button_then_confirm_is_blocked(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token, action=slack_events.CANCEL_ID), NOW)
    assert fake.updated[0][2] == "취소했어요. 아무것도 만들지 않았어요."
    slack_events.handle_action(click(token), NOW)  # 취소한 뒤 확인
    assert fake.ephemeral == [("D1", STAFF, co.MSG_DONE)] and orders(session, world) == []


# ----- chat.update 실패 -----

@pytest.mark.parametrize("error", [SlackApiError("x", {"ok": False, "error": "message_not_found"}), ConnectionError("down")])
def test_update_failure_keeps_result(client, session, world, shop, ai, fake, logs, error):
    token = propose_token(client, fake, ai, L(1))
    fake.fail_update = error
    slack_events.handle_action(click(token), NOW)  # 예외가 나오면 여기서 실패
    assert len(orders(session, world)) == 1  # 결과는 그대로
    assert "outcome=UPDATE_FAILED" in logs() and ("message_not_found" in logs() or "ConnectionError" in logs())
    assert len(fake.ephemeral) == 1 and "발주 초안을 만들었어요" in fake.ephemeral[0][2]  # 누른 사람에게는 결과를 따로 알린다
    fake.fail_update = None
    slack_events.handle_action(click(token), NOW)  # 버튼이 남아 다시 눌려도 서버가 막는다
    assert len(orders(session, world)) == 1


def test_update_and_ephemeral_both_fail_still_quiet(client, session, world, shop, ai, fake, logs):
    token = propose_token(client, fake, ai, L(1))
    fake.fail_update = fake.fail_ephemeral = ConnectionError("down")
    slack_events.handle_action(click(token), NOW)
    assert len(orders(session, world)) == 1
    assert "outcome=EPHEMERAL_FAILED" in logs()


def test_handler_error_is_contained(client, session, world, shop, ai, fake, logs, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("비밀 메모")

    monkeypatch.setattr(co, "confirm", boom)
    slack_events.handle_action(click("x.y"), NOW)
    assert "outcome=ERROR error=RuntimeError" in logs() and "비밀 메모" not in logs()
    assert fake.ephemeral == [("D1", STAFF, slack_events.ACTION_ERROR)]


# ----- payload 모양 -----

@pytest.mark.parametrize("payload", [
    {"type": "block_actions"},
    {"type": "block_actions", "user": {"id": "U1"}, "team": {"id": TEAM}, "channel": {"id": "D1"}, "actions": []},
    {"type": "block_actions", "user": "U1", "team": {"id": TEAM}, "channel": {"id": "D1"}, "container": {"message_ts": "1.1"},
     "actions": [{"action_id": slack_events.CONFIRM_ID, "value": "t"}]},
    {"type": "block_actions", "user": {"id": "U1"}, "team": {"id": TEAM}, "channel": {"id": "D1"}, "container": {"message_ts": "1.1"},
     "actions": [{"action_id": slack_events.CONFIRM_ID, "value": 5}]},
    {"type": "block_actions", "user": {"id": "U1"}, "team": {"id": TEAM}, "channel": {"id": "D1"}, "container": {"message_ts": "1.1"},
     "actions": "oops"},
])
def test_bad_payload_does_nothing(client, session, world, shop, fake, logs, payload):
    slack_events.handle_action(payload, NOW)
    assert fake.updated == [] and fake.ephemeral == [] and fake.sent == []
    assert "outcome=BAD_PAYLOAD" in logs()


def test_not_a_button_payload_is_ignored(client, session, world, shop, fake, logs):
    slack_events.handle_action({"type": "view_submission"}, NOW)
    slack_events.handle_action(click("x.y", action="something_else"), NOW)
    slack_events.handle_action("not a dict", NOW)  # type: ignore[arg-type]
    assert fake.updated == [] and fake.ephemeral == [] and logs().count("outcome=IGNORED") == 3


def test_message_ts_fallback(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    payload = click(token)
    payload["message"] = {"ts": "1700.99"}
    del payload["container"]
    slack_events.handle_action(payload, NOW)
    assert fake.updated[0][1] == "1700.99"


# ----- HTTP /slack/interactions -----

def post_click(client, payload, secret=SECRET, raw=None):
    body = raw if raw is not None else ("payload=" + quote(json.dumps(payload))).encode()
    headers = signed(body, secret=secret) | {"Content-Type": "application/x-www-form-urlencoded"}
    return client.post(INTERACTIONS, content=body, headers=headers)


def test_interactions_confirm(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    assert post_click(client, click(token)).status_code == 200  # 응답 뒤 뒤 작업에서 처리된다
    assert len(orders(session, world)) == 1 and len(fake.updated) == 1


def test_interactions_bad_signature(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    response = post_click(client, click(token), secret="wrong")
    assert response.status_code == 401 and response.json()["error"]["code"] == "SLACK_BAD_SIGNATURE"
    assert orders(session, world) == [] and fake.updated == []


def test_interactions_wrong_team(client, session, world, shop, ai, fake, logs):
    token = propose_token(client, fake, ai, L(1))
    assert post_click(client, click(token, team="T0OTHER")).status_code == 200
    assert orders(session, world) == [] and fake.updated == [] and fake.ephemeral == []
    assert "outcome=WRONG_TEAM" in logs()


@pytest.mark.parametrize("raw", [b"", b"payload=", b"payload=%7Bnot-json", b"other=1", b"payload=%5B1%5D"])
def test_interactions_unreadable_body(client, world, shop, fake, raw):
    assert post_click(client, None, raw=raw).status_code == 400
    assert fake.updated == []


def test_interactions_disabled_is_404(client, world, shop, monkeypatch):
    monkeypatch.setattr(settings, "slack_enabled", False)
    assert post_click(client, click("x.y")).status_code == 404


# ----- 토큰 길이 (버튼 value 한도 2,000자) -----

def test_twenty_line_token_fits_button_limit(client, session, world, shop, ai, fake):
    for i in range(18):  # 기존 2개 + 18개 = 20줄
        stock_50_sold_300(session, world, f"X{i:02d}")
    session.commit()
    token = propose_token(client, fake, ai, *[L(n) for n in range(1, 21)])
    assert len(co._open(token)["items"]) == 20
    assert len(token) <= 2000
    huge = co._seal({"u": 2**31, "c": 2**31, "day": "2026-11-16", "exp": 2**31, "nonce": "x" * 16,
                     "items": [[2**31, 2**31, 10**6]] * 20})  # 가장 큰 값들로 채운 20줄
    assert len(huge) <= 2000
    print(f"token length: realistic={len(token)} worst={len(huge)}")


# ----- 로그 -----

def test_logs_have_no_token_text_or_slack_ids(client, session, world, shop, ai, fake, logs):
    token = propose_token(client, fake, ai, L(1), text="비밀 메모 내용")
    slack_events.handle_action(click(token, user=ADMIN), NOW)
    slack_events.handle_action(click(token), NOW)
    slack_events.handle_action(click(token), NOW)
    send(client, "비밀 메모 내용", user=STAFF)
    for _ in range(3):
        send(client, "비밀 메모 내용", user=STAFF)  # 제한에 걸린 요청도
    text = logs()
    for secret in (token, token.split(".")[0], "비밀 메모", STAFF, ADMIN, OTHER_CO, TEAM, SECRET):
        assert secret not in text


# ----- 긴 요약 (M1): 요약은 token 속 품목을 빠짐없이 보여 줘야 한다 -----

def long_names(session, world, count=18, prefix="L"):
    """이름이 100자(& 가득 → 이스케이프하면 500자)인 추천 품목 count 개. 최신 품목이 목록 앞이므로 모두 번호 안에 든다."""
    for i in range(count):
        product = stock_50_sold_300(session, world, f"{prefix}{i:02d}")
        product.name = f"{i:02d}" + "&" * 98
    session.commit()


def section_texts(blocks):
    return [b["text"]["text"] for b in blocks if b["type"] == "section"]


def test_long_summary_shows_every_item_in_limit(client, session, world, shop, ai, fake):
    long_names(session, world, 20)  # 기존 2개 + 20개 = 22개 중 앞 20개(L00~L19)가 번호에 든다
    propose_token(client, fake, ai, *[L(n) for n in range(1, 21)])
    blocks = fake.blocks[-1]
    texts = section_texts(blocks)
    assert blocks[-1]["type"] == "actions" and len(texts) >= 2  # 버튼은 마지막, 요약은 여러 블록
    assert all(len(t) <= slack_events.BLOCK_TEXT_MAX for t in texts)  # 블록마다 한도 이하
    joined = "\n".join(texts)
    for i in range(20):
        assert f"(L{i:02d})" in joined  # 모든 SKU 가 요약 안에 있다 (token 속 20줄과 같은 내용)
    assert "&amp;" in joined and "&&" not in joined and not re.search(r"&(?!amp;)", joined)  # 이스케이프가 끊기지 않았다


def test_too_many_blocks_refuses_without_buttons(client, session, world, shop, ai, fake, monkeypatch, logs):
    long_names(session, world, 20)
    monkeypatch.setattr(slack_events, "MAX_BLOCKS", 2)  # 요약 블록 2개 + 버튼 1개 = 3 > 2
    propose_token_or_none(client, ai, *[L(n) for n in range(1, 21)])
    assert fake.sent[-1][1] == slack_events.MSG_SPLIT and fake.blocks == []
    assert orders(session, world) == [] and "outcome=SUMMARY_TOO_LONG" in logs()


def propose_token_or_none(client, ai, *lines, user=STAFF, text="전부"):
    ai.say(*lines)
    assert send(client, text, user=user).status_code == 200


def test_fit_keeps_sku_and_quantity_for_huge_line():
    line = "• " + "&" * 3000 + " (SKU-9) — 3 박스(300개) ⚠ 최소 주문량 5박스보다 적어요"
    out = slack_events._fit(line)
    assert len(out) <= slack_events.BLOCK_TEXT_MAX
    assert "(SKU-9) — 3 박스(300개)" in out and out.startswith("• ") and "…" in out  # SKU·수량은 남고 품목명이 줄었다
    assert not re.search(r"&(?!amp;)", out)  # &amp; 가 중간에서 끊기지 않았다
    other = slack_events._fit("<" * 5000)  # 품목 줄이 아닌 긴 줄도 한도 안
    assert len(other) <= slack_events.BLOCK_TEXT_MAX and not re.search(r"&(?!lt;)", other)


def test_result_text_uses_same_blocks(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    slack_events.handle_action(click(token), NOW)
    _channel, _ts, text, blocks = fake.updated[0]
    assert [b["type"] for b in blocks] == ["section"] and blocks[0]["text"]["text"] == text  # 결과 문구는 자르지 않고 그대로 블록에 든다


# ----- L1: LLM 을 기다리기 전에 DB 연결을 돌려준다 -----

def test_propose_releases_connection_before_llm(session, world, shop, ai, monkeypatch):
    seen = []
    real = ai.complete

    def probe(system, user, timeout):
        seen.append(session.in_transaction())  # LLM 이 불리는 순간 세션이 트랜잭션 밖이어야 한다
        return real(system, user, timeout)

    monkeypatch.setattr(ai, "complete", probe)
    ai.say(L(1))
    user = world["a_staff"]
    reply = co.propose(session, user.company_id, user.id, "1번 2박스", TODAY, NOW)
    assert seen == [False] and reply.token and reply.outcome == "OK"
    assert orders(session, world) == []  # 이후에도 같은 세션을 문제없이 쓴다


# ----- L2: 사유 코드로 가른다 (문구를 바꿔도 동작이 같다) -----

def test_other_person_notice_survives_message_change(client, session, world, shop, ai, fake, monkeypatch):
    token = propose_token(client, fake, ai, L(1))
    monkeypatch.setattr(co, "MSG_WRONG_USER", "다른 사람이 누를 수 없어요.")
    monkeypatch.setattr(co, "MSG_DONE", "이미 끝난 요청이에요.")
    slack_events.handle_action(click(token, user=ADMIN), NOW)
    assert fake.ephemeral == [("D1", ADMIN, "다른 사람이 누를 수 없어요.")] and fake.updated == []  # 문구가 달라도 원래 메시지는 그대로
    slack_events.handle_action(click(token), NOW)
    slack_events.handle_action(click(token), NOW)
    assert fake.ephemeral[-1] == ("D1", STAFF, "이미 끝난 요청이에요.") and len(fake.updated) == 1


def test_reply_outcomes(session, world, shop, ai):
    user = world["a_staff"]
    ai.say(L(1))
    proposed = co.propose(session, user.company_id, user.id, "1번", TODAY, NOW)
    assert proposed.outcome == "OK"
    assert co.confirm(session, user.company_id, user.id, "x.y", TODAY, NOW).outcome == "INVALID_TOKEN"
    admin = world["a_admin"]
    assert co.cancel(session, admin.company_id, admin.id, proposed.token).outcome == "WRONG_USER"
    assert co.confirm(session, user.company_id, user.id, proposed.token, TODAY, NOW).outcome == "OK"
    assert co.confirm(session, user.company_id, user.id, proposed.token, TODAY, NOW).outcome == "ALREADY_DONE"
    assert co.confirm(session, user.company_id, user.id, proposed.token, TODAY, NOW + timedelta(hours=1)).outcome == "EXPIRED"


# ----- 연결은 됐지만 지금은 못 쓰는 사용자가 자기 버튼을 누름 / payload 변형 -----

@pytest.mark.parametrize("field", ["is_active", "must_change_password"])
def test_unusable_user_clicking_own_button(client, session, world, shop, ai, fake, field):
    token = propose_token(client, fake, ai, L(1))
    setattr(world["a_staff"], field, field == "must_change_password")  # 비활성이 되거나 임시 비밀번호 상태로 돌아감
    session.commit()
    slack_events.handle_action(click(token), NOW)
    assert orders(session, world) == []  # 초안이 만들어지지 않는다
    assert fake.updated[0][2] == co.MSG_NOT_LINKED and fake.ephemeral == []  # 자기 메시지의 버튼이 안내로 바뀐다


def test_click_with_only_user_team_id(client, session, world, shop, ai, fake):
    token = propose_token(client, fake, ai, L(1))
    payload = click(token)
    del payload["team"]  # team.id 가 없고 user.team_id 만 있다
    slack_events.handle_action(payload, NOW)
    assert len(orders(session, world)) == 1


def test_click_with_wrong_user_team_id_is_ignored(client, session, world, shop, ai, fake, logs):
    token = propose_token(client, fake, ai, L(1))
    payload = click(token)
    del payload["team"]
    payload["user"]["team_id"] = "T0OTHER"
    slack_events.handle_action(payload, NOW)
    assert orders(session, world) == [] and fake.updated == [] and "outcome=WRONG_TEAM" in logs()


# ----- 표시 개선: 결과 문구·도움말·옵션 (#197 후속) -----

def test_result_text_in_slack_escapes_name_and_options(client, session, world, shop, ai, fake):
    from app.models import Product

    one = session.scalar(select(Product).where(Product.sku == "ONE"))
    one.name, one.color, one.size = "A<&>B", "<검&정>", "M&L"
    session.commit()
    token = propose_token(client, fake, ai, L(2))
    assert "A&lt;&amp;&gt;B · &lt;검&amp;정&gt; / M&amp;L (ONE)" in fake.sent[-1][1]  # 요약
    slack_events.handle_action(click(token), NOW)
    _, _, text, blocks = fake.updated[0]
    shown = text + " ".join(b["text"]["text"] for b in blocks)
    assert "A&lt;&amp;&gt;B · &lt;검&amp;정&gt; / M&amp;L (ONE) — 160개" in shown
    assert "A<&>B" not in shown and "<검&정>" not in shown


def test_result_with_20_lines_is_complete_in_blocks(client, session, world, shop, ai, fake):
    for i in range(18):
        stock_50_sold_300(session, world, f"LONG{i}")
    session.commit()
    token = propose_token(client, fake, ai, *[L(n) for n in range(1, 21)])
    slack_events.handle_action(click(token), NOW)
    _, _, _, blocks = fake.updated[0]
    shown = "\n".join(b["text"]["text"] for b in blocks)
    assert shown.count("• ") == 20 and all(f"(LONG{i})" in shown for i in range(18))  # 줄이 빠지지 않는다
    assert "승인과 발주는 웹에서 해 주세요." in shown


def test_help_lists_only_working_inputs(client, world, shop, ai, fake):
    send(client, "도움말")
    help_text = fake.sent[-1][1]
    assert "\n" in help_text and help_text.count("• ") >= 3  # 줄바꿈이 있는 짧은 목록
    for supported in ("번호와 수량", "1번 3박스", "전부", "도움말", "[확인]", "[취소]", "품목 이름"):
        assert supported in help_text
    assert "승인·발주·입고·판매는 슬랙에서 할 수 없어요" in help_text and "웹에서" in help_text
    for unsupported in ("연결 코드", "연결 1", "'취소'", "승인해", "입고해"):  # 글로 보내도 동작하지 않거나 슬랙에서 못 하는 것
        assert unsupported not in help_text
    assert ai.calls == []  # 도움말은 LLM 을 부르지 않는다
    for text, outcome in (("전부", "OK"), ("1번 3박스", "OK")):  # 도움말의 예시 입력은 실제로 요약까지 간다
        ai.say(L(1))
        send(client, text)
        assert fake.blocks and "이대로 발주 초안을 만들까요?" in fake.sent[-1][1]


def test_logs_have_no_token_text_or_slack_id_after_confirm(client, session, world, shop, ai, fake, logs):
    token = propose_token(client, fake, ai, L(2), text="비밀 메모 검정 M")
    slack_events.handle_action(click(token), NOW)
    text = logs()
    assert "slack_order action=CONFIRM outcome=OK" in text
    for secret in (token, "비밀 메모", STAFF, "ONE 이름"):
        assert secret not in text
