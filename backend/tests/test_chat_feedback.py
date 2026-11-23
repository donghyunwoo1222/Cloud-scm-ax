"""안내 챗봇 피드백(#199 PR4) 테스트: "도움이 됐어요 / 아니에요" 숫자만, 그날 답한 수를 상한으로. LLM 은 부르지 않는다."""

from datetime import date  # 통계 날짜 고정

import pytest  # 테스트 도구
from sqlalchemy import select, update  # 통계 읽기, 제약 위반 시도
from sqlalchemy.exc import IntegrityError  # DB 제약 위반

from app.config import settings  # CHAT_GUIDE_ENABLED
from app.models import ChatDailyStat  # 일별 통계 표
from app.services import chat_guide, llm  # 챗봇 서비스, LLM 래퍼 (호출되지 않는지 확인)
from tests.concurrency import run_at_once, run_in_new_session  # 진짜 commit 하는 동시 실행 도구
from tests.helpers import login_as  # 로그인 도우미

URL = "/api/v1/chat/guide/feedback"
DAY = date(2026, 11, 23)


@pytest.fixture
def on(monkeypatch):
    """챗봇을 켜고 오늘을 고정한다. LLM 클라이언트는 None: 피드백이 LLM 을 부르면 안 된다."""
    monkeypatch.setattr(settings, "chat_guide_enabled", True)
    monkeypatch.setattr(chat_guide, "seoul_today", lambda: DAY)
    monkeypatch.setattr(llm, "client", None)


def answered(session, company, n):
    """오늘 답이 n 건 있었던 상태를 만든다 (requests·answered 를 함께 올려 기존 불변식을 맞춘다)."""
    for _ in range(n):
        chat_guide.reserve(session, company.id, DAY)
    chat_guide.add(session, company.id, DAY, answered=n)


def stats(session, company):
    session.expire_all()
    row = session.scalar(select(ChatDailyStat).where(ChatDailyStat.company_id == company.id))
    return None if row is None else {n: getattr(row, n) for n in ("requests", "answered", "helpful", "not_helpful")}


def post(client, helpful):
    return client.post(URL, json={"helpful": helpful})


@pytest.mark.parametrize("email", ["staff@a.test", "admin@a.test"])
def test_helpful_and_not_helpful_add_one_without_touching_requests(client, world, session, on, email):
    answered(session, world["a_company"], 2)
    login_as(client, email)
    assert post(client, True).json() == {"data": {"recorded": True}}
    assert post(client, False).json() == {"data": {"recorded": True}}
    assert stats(session, world["a_company"]) == {"requests": 2, "answered": 2, "helpful": 1, "not_helpful": 1}


def test_feedback_cannot_exceed_answers_of_the_day(client, world, session, on):
    """오늘 답 2건 → 피드백 2건까지. 3번째는 200 recorded=false 이고 숫자는 그대로."""
    answered(session, world["a_company"], 2)
    login_as(client)
    assert [post(client, h).json()["data"]["recorded"] for h in (True, True, False)] == [True, True, False]
    assert stats(session, world["a_company"]) == {"requests": 2, "answered": 2, "helpful": 2, "not_helpful": 0}


def test_no_answers_today_records_nothing(client, world, session, on):
    """답이 없는 날(행이 없음)에는 기록하지 않고 행도 만들지 않는다."""
    login_as(client)
    assert post(client, True).json() == {"data": {"recorded": False}}
    assert stats(session, world["a_company"]) is None


def test_companies_are_separate(client, world, session, on):
    answered(session, world["a_company"], 1)
    answered(session, world["b_company"], 1)
    login_as(client, "staff@b.test")
    assert post(client, False).json()["data"]["recorded"] is True
    assert stats(session, world["a_company"])["not_helpful"] == 0
    assert stats(session, world["b_company"])["not_helpful"] == 1


def test_switch_off_is_503(client, world, session, on, monkeypatch):
    answered(session, world["a_company"], 1)
    monkeypatch.setattr(settings, "chat_guide_enabled", False)
    login_as(client)
    r = post(client, True)
    assert r.status_code == 503 and r.json()["error"]["code"] == "CHAT_DISABLED"
    assert stats(session, world["a_company"])["helpful"] == 0


def test_login_required(client, on):
    assert post(client, True).status_code == 401


@pytest.mark.parametrize("body", [
    {"helpful": True, "question": "승인은?"},  # 질문 글은 받지 않는다
    {"helpful": True, "sources": ["G-PO-APPROVE"]},  # 출처 ID 도 받지 않는다
    {"helpful": True, "company_id": 2},  # 회사는 토큰에서만
    {"helpful": "yes"},
    {"helpful": 1},
    {},
])
def test_unknown_or_loose_fields_are_422(client, world, session, on, body):
    answered(session, world["a_company"], 1)
    login_as(client)
    r = client.post(URL, json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert stats(session, world["a_company"])["helpful"] == 0


def test_db_check_blocks_feedback_over_answered(session, world):
    """서버 코드를 거치지 않고 직접 올려도 DB 제약(helpful + not_helpful <= answered)이 막는다."""
    answered(session, world["a_company"], 1)
    with pytest.raises(IntegrityError):
        session.execute(update(ChatDailyStat).where(ChatDailyStat.company_id == world["a_company"].id)
                        .values(helpful=1, not_helpful=1))
        session.flush()
    session.rollback()


def test_add_cannot_touch_feedback_columns(session, world):
    """add() 로는 피드백 칸을 올릴 수 없다 (상한 문장을 우회하지 못하게)."""
    with pytest.raises(AssertionError):
        chat_guide.add(session, world["a_company"].id, DAY, helpful=1)


def test_concurrent_feedback_stops_at_answers(engine, committed_company, on):
    """오늘 답 3건, 동시에 피드백 5건 → 정확히 3건만 기록. 확인과 증가가 UPDATE 한 문장이라서."""
    cid = committed_company["company_id"]

    def seed(s):
        for _ in range(3):
            chat_guide.reserve(s, cid, DAY)
        chat_guide.add(s, cid, DAY, answered=3)

    run_in_new_session(engine, seed)
    results = run_at_once(*[lambda: run_in_new_session(engine, lambda s: chat_guide.record_feedback(s, cid, True))] * 5)
    assert sorted(results) == [False, False, True, True, True]
    counts = run_in_new_session(engine, lambda s: s.execute(
        select(ChatDailyStat.requests, ChatDailyStat.answered, ChatDailyStat.helpful)
        .where(ChatDailyStat.company_id == cid)).one())
    assert tuple(counts) == (3, 3, 3)
