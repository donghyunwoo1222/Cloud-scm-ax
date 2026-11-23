"""안내 챗봇 서비스(#199) 테스트: 안내서 읽기, 개인정보 모양, 답변 검증, 분당 한도, 일별 통계(DB). LLM 은 부르지 않는다."""

import re  # 안내서 머리글 세기
from datetime import date  # 통계 날짜

import pytest  # 테스트 도구
from sqlalchemy import select  # 통계 행 읽기

from app.config import settings  # CHAT_GUIDE_* 설정
from app.models import ChatDailyStat  # 일별 통계 표
from app.services import chat_guide  # 테스트할 서비스
from app.services.chat_guide import GuideAnswer  # LLM 출력 모양
from tests.concurrency import run_at_once, run_in_new_session  # 진짜 commit 하는 동시 실행 도구

DAY = date(2026, 11, 23)


# ----- 안내서 -----

def test_guide_items_parsed_from_file():
    """항목 ID 목록은 파일에서 읽는다: "## [ID]" 머리글 수와 같고, 겹치지 않고, 제목이 있다."""
    heads = re.findall(r"^## \[([A-Z0-9-]+)\]", chat_guide.GUIDE_TEXT, re.MULTILINE)
    assert [i.id for i in chat_guide.ITEMS] == heads and len(heads) >= 20
    assert len(set(heads)) == len(heads)
    assert all(i.title for i in chat_guide.ITEMS)
    assert chat_guide.BY_ID["G-PO-APPROVE"].path == "/purchase-orders"


def test_new_items_need_no_code_change():
    """항목이 늘어도 코드를 고칠 필요가 없다. "준비 중"(화면: 없음)은 링크가 없다."""
    text = ("# 제목\n\n## [G-A] 첫째\n화면: /dashboard\n대상: 관리자\n상태: 사용 가능\n1. 단계\n\n"
            "## [G-NEW-2] 새 기능\n화면: 없음\n대상: 관리자·담당자\n상태: 준비 중\n")
    items = chat_guide.parse_guide(text)
    assert [(i.id, i.title, i.path, i.status) for i in items] == [
        ("G-A", "첫째", "/dashboard", "사용 가능"), ("G-NEW-2", "새 기능", None, "준비 중")]


def test_select_context_is_whole_guide_and_size_is_bounded():
    """지금은 안내서 전체를 넣는다. 30,000자를 넘으면 RAG 전환(#318)을 검토하라는 신호로 이 테스트가 깨진다."""
    assert chat_guide.select_context("질문", []) == chat_guide.GUIDE_TEXT
    assert len(chat_guide.GUIDE_TEXT) <= 30_000


# ----- 개인정보 모양 -----

@pytest.mark.parametrize("text,kinds", [
    ("제 메일 kim.a+1@example.co.kr 로 보내 주세요", ["email"]),
    ("01012345678 로 연락", ["phone"]),
    ("010-1234-5678", ["phone"]),
    ("010 1234 5678", ["phone"]),
    ("010.1234.5678", ["phone"]),
    ("011-123-4567 번호", ["phone"]),
    ("회사 02-123-4567 로", ["phone"]),
    ("031-1234-5678", ["phone"]),
    ("주민번호 900101-1234567", ["rrn"]),
    ("a@b.com 010-1111-2222", ["email", "phone"]),
])
def test_pii_blocked(text, kinds):
    assert chat_guide.pii_kinds(text) == kinds


@pytest.mark.parametrize("text", [
    "바코드 8801234567890 품목은 어떻게 등록해요?",  # 13자리 바코드 (하이픈 없는 주민번호 모양과 같다)
    "사업자등록번호 123-45-67890 은 어디에 적나요?",
    "2026-11-23 에 입고한 것 정정",
    "발주번호 PO-20261123-0001 승인 방법",
    "품목코드 SKU-0001-BLK-L 수정",
    "0212345678 상품코드",  # 지역번호 전화는 구분자 있을 때만 막는다
    "수량 1,000개를 30일 동안",
    "9001011234567",  # 하이픈 없는 13자리는 막지 않는다 (바코드 오탐 방지)
])
def test_pii_not_blocked(text):
    assert chat_guide.pii_kinds(text) == []


def test_pii_findings_report_place_and_kind_only():
    """어디에 어떤 종류가 있는지만 알려 주고 원문은 담지 않는다."""
    found = chat_guide.pii_findings("010-1234-5678 승인?", [{"question": "괜찮은 질문", "sources": []},
                                                          {"question": "a@b.com", "sources": []}])
    assert found == [{"where": "question", "kinds": ["phone"]}, {"where": "history", "index": 1, "kinds": ["email"]}]
    assert "1234" not in str(found) and "a@b" not in str(found)


# ----- 답변 검증 -----

def answer(kind="ANSWER", text="관리자가 승인합니다.", sources=("G-PO-APPROVE",)):
    return GuideAnswer(kind=kind, answer=text, sources=list(sources))


def test_finalize_keeps_real_sources_and_builds_links_on_server():
    out = chat_guide.finalize(answer(sources=["G-PO-APPROVE", "G-FAKE", "G-PO-APPROVE", "G-STOCK"]))
    assert out["kind"] == "ANSWER"
    assert [s["id"] for s in out["sources"]] == ["G-PO-APPROVE", "G-STOCK"]  # 없는 ID 버림, 중복 제거
    many = chat_guide.finalize(answer(sources=["G-PO-APPROVE", "G-STOCK", "G-RECO", "G-USERS"]))
    assert [s["id"] for s in many["sources"]] == ["G-PO-APPROVE", "G-STOCK", "G-RECO"]  # 3개까지
    assert out["sources"][0] == {"id": "G-PO-APPROVE", "title": "발주서 승인 (관리자만)", "path": "/purchase-orders"}


def test_answer_without_real_source_becomes_not_found():
    for sources in ([], ["G-FAKE"], ["https://evil.example"]):
        out = chat_guide.finalize(answer(sources=sources))
        assert out == {"kind": "NOT_FOUND", "answer": chat_guide.NOT_FOUND_TEXT, "sources": []}


def test_urls_in_answer_are_removed():
    out = chat_guide.finalize(answer(text="여기 https://evil.example/x 와 www.evil.example 를 누르세요"))
    assert "evil" not in out["answer"] and "http" not in out["answer"]
    assert chat_guide.finalize(answer(text="https://evil.example"))["kind"] == "NOT_FOUND"  # 주소만 있던 답은 근거 없는 답


def test_not_found_and_data_question_use_fixed_text():
    nf = chat_guide.finalize(answer(kind="NOT_FOUND", text="아마 이럴 거예요", sources=["G-STOCK"]))
    assert nf == {"kind": "NOT_FOUND", "answer": chat_guide.NOT_FOUND_TEXT, "sources": []}
    dq = chat_guide.finalize(answer(kind="DATA_QUESTION", text="재고는 52개입니다", sources=["G-STOCK"]))
    assert dq["answer"] == chat_guide.DATA_TEXT and dq["sources"][0]["path"] == "/inventory"


# ----- 분당 한도 -----

def test_per_minute_limit_with_fake_clock(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(chat_guide, "now", lambda: t[0])
    monkeypatch.setattr(settings, "chat_guide_per_minute", 5)
    chat_guide.reset()
    for at in (0, 10, 20, 30, 40):
        t[0] = at
        assert chat_guide.take_slot(1) is None
    t[0] = 50
    assert chat_guide.take_slot(1) == 10  # 0초 기록이 빠지는 60초까지 10초
    assert chat_guide.take_slot(2) is None  # 다른 사용자는 따로 센다
    t[0] = 60
    assert chat_guide.take_slot(1) is None
    chat_guide.reset()


# ----- 일별 통계 (DB) -----

def row(session, company_id):
    session.expire_all()
    return session.scalar(select(ChatDailyStat).where(ChatDailyStat.company_id == company_id))


def test_reserve_stops_at_daily_cap_per_company(session, world, monkeypatch):
    monkeypatch.setattr(settings, "chat_guide_daily_per_company", 2)
    a, b = world["a_company"].id, world["b_company"].id
    assert [chat_guide.reserve(session, a, DAY) for _ in range(3)] == [True, True, False]
    assert chat_guide.reserve(session, b, DAY) is True  # 다른 회사는 영향 없음
    assert chat_guide.reserve(session, a, date(2026, 11, 24)) is True  # 다음 날은 새로 센다
    assert row(session, a).requests == 2


def test_add_only_known_counter_columns(session, world):
    a = world["a_company"].id
    chat_guide.add(session, a, DAY, blocked_pii=1)
    chat_guide.add(session, a, DAY, limited=2, tokens_in=7000)
    r = row(session, a)
    assert (r.requests, r.blocked_pii, r.limited, r.tokens_in) == (0, 1, 2, 7000)  # 막힌 요청은 requests 에 안 센다
    with pytest.raises(AssertionError):
        chat_guide.add(session, a, DAY, requests=1)  # requests 는 reserve 만 올린다
    with pytest.raises(AssertionError):
        chat_guide.add(session, a, DAY, question=1)  # 목록 밖 칸 금지


def test_stats_table_has_no_text_columns():
    """질문·답변 글을 담을 칸이 없다: 날짜·시각 말고는 모두 정수."""
    kinds = {c.name: c.type.python_type for c in ChatDailyStat.__table__.columns}
    assert {n for n, t in kinds.items() if t not in (int,)} == {"day", "created_at", "updated_at"}


def test_reserve_holds_under_concurrent_requests(engine, committed_company, monkeypatch):
    """상한 3, 이미 2번 쓴 상태에서 동시에 5건 → 1건만 통과. 확인과 증가가 SQL 한 문장이라 101번째가 생기지 않는다."""
    monkeypatch.setattr(settings, "chat_guide_daily_per_company", 3)
    cid = committed_company["company_id"]
    for _ in range(2):
        run_in_new_session(engine, lambda s: chat_guide.reserve(s, cid, DAY))
    results = run_at_once(*[lambda: run_in_new_session(engine, lambda s: chat_guide.reserve(s, cid, DAY))] * 5)
    assert sorted(results) == [False, False, False, False, True]
    assert run_in_new_session(engine, lambda s: row(s, cid).requests) == 3
