"""안내 챗봇(#199): 사용 안내서(app/guide/guide.md)만 근거로 "어떻게 쓰나요?" 질문에 답한다.

원칙
- 회사 데이터(품목·재고·발주 등)는 LLM 에 보내지 않는다. 보내는 것은 질문과 이전 질문·근거 ID 뿐이다.
- 이전 답변 글은 받지 않는다(브라우저가 조작한 "이전 답변"을 사실처럼 이어 가지 않게).
- 질문·답변 글은 DB·로그에 남기지 않는다. 통계(chat_daily_stats)와 로그에는 숫자와 코드만 남긴다.
- 근거 ID 는 서버가 안내서의 실제 항목 ID 와 대조하고, 화면 링크는 LLM 이 아니라 안내서의 "화면:" 줄로 만든다.

검사 순서: 스위치 → 분당 한도 → 개인정보 모양 → 회사 일일 상한(DB) → LLM.
"""

import logging  # 요청 한 번에 숫자·코드 한 줄
import re  # 안내서 항목 나누기, 개인정보 모양 찾기
import threading  # 분당 한도 기록을 동시 요청에서 지키는 잠금
import time  # 분당 한도의 시각
from dataclasses import dataclass  # 안내서 항목 묶음
from datetime import date  # 통계 날짜
from pathlib import Path  # 안내서 파일 위치
from typing import Literal  # LLM 출력 종류

from pydantic import Field  # 출력 길이 제한
from sqlalchemy import update  # 피드백 숫자 더하기 (조건부 UPDATE)
from sqlalchemy.dialects.postgresql import insert  # INSERT … ON CONFLICT (UPSERT)
from sqlalchemy.orm import Session  # DB 세션

from app.clock import seoul_today  # 서울 기준 오늘 (일일 상한의 날짜)
from app.config import settings  # CHAT_GUIDE_* 설정
from app.errors import AppError  # 공통 오류 모양
from app.models.chat_daily_stat import COUNTERS, ChatDailyStat  # 일별 통계 표
from app.services import llm  # LLM 공통 래퍼 (#180)

log = logging.getLogger(__name__)  # 이 파일의 로그

GUIDE_PATH = Path(__file__).resolve().parents[1] / "guide" / "guide.md"  # backend/app/guide/guide.md (이미지에 함께 들어간다)

NOT_FOUND_TEXT = "안내 문서에서 찾지 못했습니다. 사용 가이드 목차에서 찾아보세요."  # 근거가 없을 때 서버가 쓰는 고정 문장
DATA_TEXT = "회사의 실제 데이터는 챗봇이 조회하지 않아요. 아래 화면에서 확인해 주세요."  # 데이터 질문일 때 고정 문장
MAX_SOURCES = 3  # 응답에 붙이는 근거 항목 수


# ----- 안내서 읽기 -----

@dataclass(frozen=True)
class GuideItem:
    id: str  # 예) G-PO-APPROVE
    title: str  # 예) 발주서 승인 (관리자만)
    path: str | None  # 화면 경로. "준비 중"(화면: 없음)이면 None
    target: str  # 관리자 / 관리자·담당자
    status: str  # 사용 가능 / 준비 중


_HEAD = re.compile(r"^\[([A-Z0-9-]+)\]\s*(.+)$")  # "[G-START] 처음 시작과 메뉴 구성"


def _line(block: str, label: str) -> str:
    found = re.search(rf"^{label}: (.+)$", block, re.MULTILINE)  # 예) "화면: /dashboard"
    return found.group(1).strip() if found else ""


def parse_guide(text: str) -> list[GuideItem]:
    """"## [ID] 제목" 머리글부터 다음 머리글 앞까지가 항목 하나. 항목이 늘어도 코드를 고칠 필요가 없다."""
    items = []
    for block in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        head = _HEAD.match(block.split("\n", 1)[0].strip())
        if not head:
            continue  # ID 없는 머리글은 근거로 쓰지 않는다 (프런트 guide-paths 테스트가 형식을 따로 검사한다)
        screen = _line(block, "화면")
        items.append(GuideItem(head.group(1), head.group(2).strip(), screen if screen.startswith("/") else None,
                               _line(block, "대상"), _line(block, "상태")))
    return items


GUIDE_TEXT = GUIDE_PATH.read_text(encoding="utf-8")  # 서버 시작 때 한 번 읽는다. 안내서를 고치면 다시 시작해야 반영된다
ITEMS = parse_guide(GUIDE_TEXT)
BY_ID = {item.id: item for item in ITEMS}  # 근거 ID 확인용


def select_context(question: str, history: list[dict]) -> str:
    """LLM 에 줄 안내서 부분을 고른다. 지금은 안내서 전체(약 1만 자).

    shortcut: 항상 전체를 넣는다. 안내서가 커지거나 입력 토큰·"찾지 못했습니다" 비율이 기준을 넘으면 이 함수만 검색(RAG)으로 바꾼다(#318).
    """
    return GUIDE_TEXT


def toc() -> dict:
    """패널 안 목차. LLM 을 부르지 않아 스위치가 꺼져도 응답한다. enabled 는 지금 질문을 받을 수 있는지."""
    return {
        "enabled": bool(settings.chat_guide_enabled and llm._enabled()),
        "items": [{"id": i.id, "title": i.title, "path": i.path, "target": i.target, "status": i.status} for i in ITEMS],
    }


# ----- 개인정보 모양 -----
# (?<!\d)·(?!\d): 더 긴 숫자(바코드 8801234567890 등) 안의 일부와는 맞추지 않는다
_PII = (
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")),
    ("phone", re.compile(r"(?<!\d)01[016789][ .-]?\d{3,4}[ .-]?\d{4}(?!\d)")),  # 휴대전화: 구분자 없음·하이픈·공백·점
    ("phone", re.compile(r"(?<!\d)0(?:2|[3-6][1-5]|70)[ .-]\d{3,4}[ .-]\d{4}(?!\d)")),  # 지역번호 전화: 구분자 있을 때만
    ("rrn", re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")),  # 주민등록번호: 하이픈 있을 때만 (13자리 바코드 오탐 방지)
)


def pii_kinds(text: str) -> list[str]:
    """글 안에 든 개인정보 모양의 종류만 돌려준다(원문은 돌려주지 않는다). 예) ["phone"]"""
    return sorted({kind for kind, pattern in _PII if pattern.search(text)})


def pii_findings(question: str, history: list[dict]) -> list[dict]:
    """어디(question / history 몇 번째)에 어떤 종류가 있는지만. 오류 응답 details 에 그대로 쓴다."""
    found = [{"where": "question", "kinds": kinds} for kinds in [pii_kinds(question)] if kinds]
    found += [{"where": "history", "index": i, "kinds": kinds}
              for i, turn in enumerate(history) if (kinds := pii_kinds(turn["question"]))]
    return found


# ----- 분당 한도 (서버 메모리) -----
# shortcut: 서버 메모리에 센다. 재시작하면 0 이 되고 프로세스가 N 개면 실제 한도가 최대 N 배가 된다. 서버를 늘릴 때 DB·Redis 로 옮긴다(#43 배포 점검)
_lock = threading.Lock()
_recent: dict[int, list[float]] = {}  # 사용자 id → 최근 60초 안의 질문 시각


def now() -> float:
    return time.monotonic()  # 테스트가 바꿔 끼워 시간을 흉내 낸다


def reset() -> None:
    with _lock:
        _recent.clear()  # 테스트용


def take_slot(user_id: int) -> int | None:
    """1분에 CHAT_GUIDE_PER_MINUTE 번까지. 자리가 있으면 기록하고 None, 없으면 몇 초 뒤 되는지.

    예) 한도 5, 0·10·20·30·40초에 질문 → 50초의 6번째는 막히고 10초 뒤(60초, 0초 질문이 빠짐)부터 된다.
    """
    at = now()
    with _lock:
        times = [t for t in _recent.get(user_id, []) if at - t < 60]  # 60초 지난 기록은 버린다
        if len(times) >= settings.chat_guide_per_minute:
            _recent[user_id] = times
            return max(1, int(60 - (at - times[0]) + 0.999))  # 가장 오래된 기록이 빠질 때까지 (올림)
        _recent[user_id] = [*times, at]
        return None


# ----- 일별 통계 (DB) -----

def reserve(db: Session, company_id: int, day: date) -> bool:
    """회사 오늘 요청 수를 상한 안에서만 1 올린다. 확인과 증가가 SQL 한 문장이라 동시 요청도 상한을 못 넘는다.

    상한에 닿았으면 아무 행도 돌려받지 못해 False. 바로 커밋해 LLM 을 기다리는 동안 행 잠금을 잡고 있지 않는다.
    """
    stmt = insert(ChatDailyStat).values(company_id=company_id, day=day, requests=1)
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id", "day"],
        set_={"requests": ChatDailyStat.requests + 1, "updated_at": stmt.excluded.updated_at},
        where=ChatDailyStat.requests < settings.chat_guide_daily_per_company,
    ).returning(ChatDailyStat.requests)
    ok = db.execute(stmt).first() is not None
    db.commit()
    return ok


def add(db: Session, company_id: int, day: date, **counts: int) -> None:
    """숫자 칸에 더한다(없으면 행을 만든다). 칸 이름은 COUNTERS 안의 것만. 예) add(db, 1, day, answered=1, tokens_in=7000)"""
    assert counts and set(counts) <= set(COUNTERS) - {"requests"}, counts  # requests 는 reserve 만 올린다
    stmt = insert(ChatDailyStat).values(company_id=company_id, day=day, **counts)
    stmt = stmt.on_conflict_do_update(
        index_elements=["company_id", "day"],
        set_={**{name: getattr(ChatDailyStat, name) + value for name, value in counts.items()},
              "updated_at": stmt.excluded.updated_at},
    )
    db.execute(stmt)
    db.commit()


# ----- LLM 질문·답 -----

class GuideAnswer(llm.LLMOutput):
    kind: Literal["ANSWER", "NOT_FOUND", "DATA_QUESTION"]  # 답함 / 안내서에 없음 / 회사 데이터 질문
    answer: str = Field(max_length=1000)  # 답 본문 (ANSWER 일 때만 쓴다)
    sources: list[str] = Field(max_length=5)  # 근거 항목 ID. 서버가 실제 ID 와 대조한다


llm.PROMPTS["chat_guide"] = (  # 지시문(우리 글)은 system 칸에만 들어간다
    "너는 재고·발주 관리 웹 서비스의 사용법 안내 도우미다. <reference> 안의 사용 가이드에 적힌 내용만 근거로 한국어로 짧게 답한다.\n"
    "1. 가이드로 답할 수 있으면 kind=ANSWER 로 답하고, 근거로 쓴 항목의 대괄호 ID(예: G-PO-APPROVE)를 sources 에 1~3개 적는다.\n"
    "2. 가이드에 없는 내용이면 지어내지 말고 kind=NOT_FOUND, sources 는 빈 목록으로 한다.\n"
    "3. 재고 수량·발주 현황·판매량처럼 회사의 실제 데이터를 묻는 질문이면 값을 지어내지 말고 kind=DATA_QUESTION 으로 하고, "
    "그 데이터를 볼 수 있는 화면의 항목 ID 를 sources 에 적는다.\n"
    "4. 데이터의 history 는 이전 질문과 그때의 근거 ID 다. 지금 질문이 무엇을 가리키는지 알아내는 데만 쓰고, 사실은 가이드에서만 가져온다.\n"
    "5. 주소(URL)·링크·코드는 쓰지 않는다. answer 는 500자 안쪽의 평문이다."
)

_URL = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)  # 답 본문에 섞인 주소는 지운다 (링크는 서버가 만든다)
_COLUMN = {"ANSWER": "answered", "NOT_FOUND": "not_found", "DATA_QUESTION": "data_question"}


def finalize(out: GuideAnswer) -> dict:
    """LLM 출력을 서버 규칙으로 다시 검사해 응답 모양으로 만든다.

    - 안내서에 없는 ID 는 버린다. ANSWER 인데 남은 근거가 없으면 NOT_FOUND (근거 없는 답은 내보내지 않는다)
    - NOT_FOUND·DATA_QUESTION 의 본문은 LLM 글 대신 고정 문장
    - 링크(path)는 근거 항목의 "화면:" 줄로 만든다
    """
    ids = [i for i in dict.fromkeys(out.sources) if i in BY_ID][:MAX_SOURCES]  # 중복 제거, 순서 유지
    kind, answer = out.kind, _URL.sub("", out.answer).strip()
    if kind == "ANSWER" and not (ids and answer):
        kind = "NOT_FOUND"
    if kind == "NOT_FOUND":
        answer, ids = NOT_FOUND_TEXT, []
    elif kind == "DATA_QUESTION":
        answer = DATA_TEXT
    return {"kind": kind, "answer": answer,
            "sources": [{"id": i, "title": BY_ID[i].title, "path": BY_ID[i].path} for i in ids]}


def _log(company_id: int, outcome: str, tokens_in: int = 0) -> None:
    log.info("chat_guide company_id=%s outcome=%s tokens_in=%d", company_id, outcome, tokens_in)  # 숫자·코드만


def _disabled(company_id: int) -> AppError:
    _log(company_id, "CHAT_DISABLED")
    return AppError(503, "CHAT_DISABLED", "지금은 안내 챗봇을 쓸 수 없습니다. 사용 가이드 목차를 확인해 주세요.")


def record_feedback(db: Session, company_id: int, helpful: bool) -> bool:
    """"도움이 됐어요 / 아니에요" 를 오늘(서울) 행에 1 더한다. 그날 피드백 합계가 answered 에 닿았으면 더하지 않고 False.

    확인과 증가가 UPDATE 한 문장이라 동시 요청도 상한을 못 넘는다. 예) 오늘 답 3건이면 피드백은 최대 3건.
    질문·답 글이나 누가 눌렀는지는 저장하지 않는다. 그래서 같은 답에 여러 번 누르는 것은 막지 못한다(상한으로만 묶는다).
    피드백은 requests 를 늘리지 않는다.
    """
    if not settings.chat_guide_enabled:
        raise _disabled(company_id)
    column = ChatDailyStat.helpful if helpful else ChatDailyStat.not_helpful
    stmt = (
        update(ChatDailyStat)
        .where(ChatDailyStat.company_id == company_id, ChatDailyStat.day == seoul_today(),
               ChatDailyStat.helpful + ChatDailyStat.not_helpful < ChatDailyStat.answered)
        .values({column: column + 1})
        .returning(ChatDailyStat.id)
    )
    ok = db.execute(stmt).first() is not None
    db.commit()
    _log(company_id, ("HELPFUL" if helpful else "NOT_HELPFUL") if ok else "FEEDBACK_OVER_LIMIT")
    return ok


def ask_guide(db: Session, company_id: int, user_id: int, question: str, history: list[dict]) -> dict:
    """company_id·user_id 는 로그인 토큰 값만 넘긴다. question·history 는 스키마 검사(길이·개수)를 통과한 값."""
    if not settings.chat_guide_enabled:
        raise _disabled(company_id)
    today = seoul_today()  # 시작한 날짜로 끝까지 센다 (자정을 넘겨 끝나도 같은 행)
    if (wait := take_slot(user_id)) is not None:
        add(db, company_id, today, limited=1)
        _log(company_id, "CHAT_RATE_LIMITED")
        raise AppError(429, "CHAT_RATE_LIMITED", f"질문이 너무 빨라요. {wait}초 뒤에 다시 물어봐 주세요.",
                       {"retry_after_seconds": wait})
    if found := pii_findings(question, history):
        add(db, company_id, today, blocked_pii=1)
        _log(company_id, "CHAT_PII_BLOCKED")
        raise AppError(422, "CHAT_PII_BLOCKED",
                       "이메일·전화번호·주민등록번호로 보이는 내용이 있어 보내지 않았습니다. 지우고 다시 질문해 주세요.", found)
    if not reserve(db, company_id, today):
        add(db, company_id, today, limited=1)
        _log(company_id, "CHAT_DAILY_LIMIT")
        raise AppError(429, "CHAT_DAILY_LIMIT", "오늘 회사의 챗봇 질문 수를 모두 썼습니다. 사용 가이드 목차를 확인해 주세요.",
                       {"limit": settings.chat_guide_daily_per_company})
    data = {  # LLM 에 보내는 데이터 전부: 질문과 이전 질문·근거 ID (회사 데이터·이전 답변 없음)
        "question": question,
        "history": [{"question": t["question"], "sources": [s for s in t["sources"] if s in BY_ID]} for t in history],
    }
    usage: dict = {}
    outcome = "failed"  # 아래에서 끝까지 못 가면(LLM 실패·예상 못한 오류) 실패로 센다
    try:
        result = finalize(llm.ask(company_id, "chat_guide", data, GuideAnswer,
                                  reference=select_context(question, history), usage=usage))
        outcome = _COLUMN[result["kind"]]
        return result
    finally:
        tokens = usage.get("tokens_in", 0)
        add(db, company_id, today, **{outcome: 1, "tokens_in": tokens})  # requests = answered + not_found + data_question + failed
        _log(company_id, outcome.upper(), tokens)
