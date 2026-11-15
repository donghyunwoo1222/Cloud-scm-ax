"""슬랙에서 오는 이벤트를 받는 어댑터 (#197 PR 3, 5b). 슬랙 모양을 해석하고, 업무 판단은 서비스(redeem_code·chat_order 등)에 맡긴다.

흐름: 받는 쪽(HTTP 경로·Socket 워커)이 먼저 "받았음"을 보내고 → 뒤에서 handle_event 가 처리한다.
슬랙은 3초 안에 답이 없으면 같은 이벤트를 최대 3번 다시 보내므로(바로·1분·5분) event_id 로 한 번만 처리한다.
  - 연결된 사용자: idempotency_keys(회사는 slack_links 행에서)에 event_id 를 먼저 잡는다.
  - 연결 전 사용자: 회사를 모르므로 서버 메모리의 최근 event_id 목록으로 건너뛴다.
회사 분리: company_id 는 언제나 slack_links 행에서만 가져온다. 슬랙 본문의 값으로 회사를 정하지 않는다.
로그: 사유 코드와 event_id 만 남긴다. 메시지 원문·연결 코드·토큰·슬랙 사용자 id 는 남기지 않는다.

PR 5b: 연결된 사용자의 글은 chat_order.propose 로 보내 요약 + [확인][취소] 버튼으로 답하고, 버튼은 handle_action 이 confirm·cancel 로 잇는다.
  - 버튼 value 에는 chat_order 가 준 토큰만 넣는다(슬랙 한도 2,000자, 품목 20줄도 그 안).
  - 누른 사람도 slack_links 행으로만 알아낸다(슬랙이 보낸 user.id·team.id 로 행을 찾고, 회사·사용자는 그 행의 값).
  - 두 번 클릭 방어는 서버의 nonce(chat_order)가 본 방어선이고, 버튼을 결과 문구로 바꾸는 chat.update 는 보조다. update 가 실패해도 결과는 그대로다.
"""

import logging  # 사유 코드 한 줄
import re  # "연결 123456" 모양
import threading  # 최근 event_id 목록을 여러 스레드가 함께 만진다
from collections import (  # 넣은 순서대로 오래된 것부터 지우기, 사람별 최근 호출 시각
    OrderedDict,
    deque,
)
from collections.abc import Mapping  # 요청 헤더 타입
from dataclasses import dataclass  # DM 한 통의 필요한 값만
from datetime import datetime, timedelta  # 처리 시각, 메모리 만료

from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답 (error 코드만 남긴다)
from slack_sdk.signature import SignatureVerifier  # 서명 검증 (5분 시각 검사 + 상수 시간 비교)
from sqlalchemy import select  # 연결 행 조회
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL  # 서울 날짜 (추천·확인 토큰의 "오늘")
from app.config import settings  # SLACK_TEAM_ID·SLACK_SIGNING_SECRET·APP_BASE_URL
from app.db import SessionLocal  # 뒤 작업 전용 세션 (요청 세션은 응답 뒤 이미 닫혀 있다)
from app.models import SlackLink  # 슬랙 연결 표
from app.services import (  # 중복 막기, 메시지 보내기, 연결 코드, 채팅 발주
    chat_order,
    idempotency,
    slack_client,
    slack_link,
)
from app.services.slack_digest import _escape  # & < > 바꾸기 (아침 DM 과 같은 규칙)

log = logging.getLogger(__name__)

EVENT_ENDPOINT = "slack:event"  # idempotency_keys 의 endpoint 칸 (웹 경로와 겹치지 않는 이름)
LINK_PATTERN = re.compile(r"연결\s*(\S+)")  # "연결 123456" (코드 모양 검사는 redeem_code 가 한다)
LINKED = "연결됐어요."
ALREADY_LINKED = "이미 연결돼 있어요."
NOT_LINKED = "먼저 웹에서 연결 코드를 받아 연결해 주세요."
HELP = (  # "도움말": 서버가 직접 답한다(LLM 없음). 실제로 동작하는 입력만 적는다
    "*이렇게 보내 주세요*\n"
    "• 번호와 수량: `1번 3박스`, `2번 50개`\n"
    "• 품목 이름: `검정 M 티셔츠 3개`\n"
    "• 전부: 추천 목록의 모든 품목을 추천 수량으로\n"
    "• 도움말: 이 안내 다시 보기\n"
    "\n"
    "*보내면 이렇게 진행돼요*\n"
    "1. 요약과 [확인][취소] 버튼이 와요\n"
    "2. [확인]을 누르면 발주 초안이 만들어지고, [취소]를 누르면 아무것도 만들지 않아요\n"
    "\n"
    "승인·발주·입고·판매는 슬랙에서 할 수 없어요. 웹에서 해 주세요."
)
CANCEL_IDLE = "취소할 요청이 없어요. 요약 메시지의 [취소]를 누르거나 그냥 두면 아무것도 만들어지지 않아요."  # "취소" 글: 서버가 직접 답한다
RATE_LIMITED = "요청이 너무 잦아요. 1분쯤 기다렸다가 다시 보내 주세요. (도움말은 언제든 볼 수 있어요)"
ACTION_ERROR = "처리 중 문제가 생겼어요. 웹에서 확인해 주세요."
RATE_PER_MINUTE = 10  # 사람별 분당 해석(LLM) 요청 수. 임시값(처음 3회는 입력을 몇 번 고치면 막혀 불편해 10회로. 비용 방어선은 회사 하루 상한)
CONFIRM_ID, CANCEL_ID = "order_confirm", "order_cancel"  # 버튼 action_id
WEB_ORDERS_PATH = "/purchase-orders"  # 발주서 목록 화면
MSG_SPLIT = "한 번에 보여 줄 수 없을 만큼 길어요. 나눠서 요청해 주세요."  # 요약이 슬랙 블록 한도를 넘을 때(버튼 없이 거절)
BLOCK_TEXT_MAX = 2900  # section 글 한도(슬랙 3,000자)에서 여유를 둔 값. 이스케이프(& → &amp;) 뒤 길이로 잰다
MAX_BLOCKS = 50  # 메시지당 블록 한도(버튼 블록 포함)
ITEM_LINE = re.compile(r"(• )(.*?)( \([^()]*\) — .*)", re.DOTALL)  # chat_order 요약의 품목 줄: "• 품목명 (SKU) — 수량"

SEEN_MAX = 1000  # 메모리에 기억할 최근 event_id 수
SEEN_MINUTES = 10  # 슬랙 재전송은 5분 뒤가 마지막이라 10분이면 덮인다

# shortcut: 연결 전 사용자의 event_id 는 서버 메모리에만 둔다. 재시작하면 잊고, 프로세스가 여러 개면 서로 모른다.
#           재전송이 다른 프로세스로 가면 틀린 코드가 한 번 더 셀 수 있다. 서버를 늘릴 때(#43) DB 로 옮길지 정한다.
_seen: OrderedDict[str, datetime] = OrderedDict()  # event_id → 처음 본 시각
_seen_lock = threading.Lock()

# shortcut: 사람별 분당 제한도 서버 메모리에만 둔다. 재시작하면 잊고 프로세스마다 따로 센다. 회사 하루 한도(LLM_DAILY_CALLS_PER_COMPANY)는 그대로라
#           천천히 계속 보내는 한 사람이 쓰는 것은 못 막는다. 서버를 늘리거나(#43) 사람별 하루 상한이 필요해지면 DB·설정으로 옮긴다.
_calls: dict[tuple[int, int], deque[datetime]] = {}  # (회사 id, 사용자 id) → 최근 1분 안의 해석 요청 시각


@dataclass(frozen=True)
class Dm:
    """처리할 DM 한 통. 슬랙 봉투에서 필요한 값만 꺼낸 것."""

    event_id: str
    team_id: str
    user: str  # 보낸 슬랙 사용자 id (U…)
    channel: str  # DM 채널 id (D…), 답장을 보낼 곳
    text: str
    thread_ts: str | None  # 스레드 안의 메시지면 그 스레드에 답한다


def reset() -> None:
    with _seen_lock:
        _seen.clear()  # 테스트용
        _calls.clear()


def _purge(at: datetime) -> None:
    """10분 지난 것과 1,000개를 넘는 것을 오래된 것부터 지운다. _seen_lock 안에서만 부른다."""
    while _seen and (len(_seen) >= SEEN_MAX or next(iter(_seen.values())) <= at - timedelta(minutes=SEEN_MINUTES)):
        _seen.popitem(last=False)


def _was_seen(event_id: str, at: datetime) -> bool:
    with _seen_lock:
        _purge(at)
        return event_id in _seen


def _remember(event_id: str, at: datetime) -> bool:
    """처음 보는 event_id 면 기억하고 True, 10분 안에 본 적 있으면 False."""
    with _seen_lock:
        _purge(at)
        if event_id in _seen:
            return False
        _seen[event_id] = at
        return True


def _rate_limited(company_id: int, user_id: int, at: datetime) -> bool:
    """이 사람의 최근 1분 해석 요청이 이미 RATE_PER_MINUTE 번이면 True(세지 않는다), 아니면 이번을 세고 False.
    예) 10초 안에 5번 보내면 3번은 LLM 까지 가고 2번은 막힌다."""
    with _seen_lock:
        recent = _calls.setdefault((company_id, user_id), deque())
        while recent and recent[0] <= at - timedelta(minutes=1):
            recent.popleft()
        if len(recent) >= RATE_PER_MINUTE:
            return True
        recent.append(at)
        return False


def _forget(event_id: str) -> None:
    with _seen_lock:
        _seen.pop(event_id, None)  # 처리 중 오류: 재전송 때 다시 처리할 수 있게


def verify(body: bytes, headers: Mapping[str, str]) -> bool:
    """HTTP 경로용 서명 검증. 파싱 전 원문 본문으로 v0:{시각}:{본문} 의 HMAC-SHA256 을 비교하고, 5분 넘은 시각은 거부한다."""
    secret = settings.slack_signing_secret.get_secret_value()
    if not secret:  # 빈 키로는 아무것도 통과시키지 않는다
        return False
    return SignatureVerifier(secret).is_valid_request(body, dict(headers))


def parse_dm(envelope: dict) -> Dm | None:
    """사람이 봇에게 보낸 새 DM 이면 Dm, 그 밖(봇 자신·수정·삭제·채널 메시지 등)은 None."""
    event = envelope.get("event") or {}
    if envelope.get("type") != "event_callback" or event.get("type") != "message" or event.get("channel_type") != "im":
        return None
    if event.get("subtype") or event.get("bot_id"):  # 수정·삭제·봇 메시지는 subtype 이나 bot_id 가 붙는다
        return None
    bot_users = {a.get("user_id") for a in envelope.get("authorizations") or []}  # 이 설치의 봇 사용자 id
    user, channel, text = event.get("user"), event.get("channel"), event.get("text")
    if not (user and channel and isinstance(text, str) and envelope.get("event_id")) or user in bot_users:
        return None
    return Dm(envelope["event_id"], envelope.get("team_id") or "", user, channel, text, event.get("thread_ts"))


def _section(escaped: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": escaped}}  # 이미 이스케이프하고 한도 이하로 맞춘 글


def _fit(line: str) -> str:
    """한 줄을 이스케이프한 글(BLOCK_TEXT_MAX 이하)로 만든다. 넘으면 품목 줄은 품목명만 줄여(SKU·수량은 남김) 맞추고, 그 밖의 줄은 끝을 줄인다.
    이스케이프 '뒤'에 길이를 재서 &amp; 가 중간에서 끊기지 않는다. 품목명은 100자 이하라 실제로는 거의 안 넘는다."""
    if len(_escape(line)) <= BLOCK_TEXT_MAX:
        return _escape(line)
    match = ITEM_LINE.fullmatch(line)
    head, name, tail = match.groups() if match else ("", line, "")
    while name and len(_escape(f"{head}{name}…{tail}")) > BLOCK_TEXT_MAX:
        name = name[:-1]
    return _escape(f"{head}{name}…{tail}")


def _text_blocks(text: str) -> list[dict]:
    """글 전체를 줄 단위로 section 블록 여러 개로 나눈다(블록마다 BLOCK_TEXT_MAX 이하). 자르지 않으니 모든 줄이 보인다."""
    blocks: list[dict] = []
    current = ""
    for line in text.split("\n"):
        piece = _fit(line)
        if current and len(current) + 1 + len(piece) > BLOCK_TEXT_MAX:
            blocks.append(_section(current))
            current = piece
        else:
            current = f"{current}\n{piece}" if current else piece
    if current:
        blocks.append(_section(current))
    return blocks


def _order_blocks(text: str, token: str) -> list[dict] | None:
    """요약 글(여러 블록) + 마지막에 [확인][취소] 버튼. 두 버튼의 value 는 같은 토큰 하나뿐이다.
    확인 버튼은 토큰 속 품목을 전부 만들므로 요약이 전부 보여야 한다. 블록이 한도를 넘으면 None(버튼 없이 거절)."""
    def button(label: str, action_id: str, **extra) -> dict:
        return {"type": "button", "action_id": action_id, "text": {"type": "plain_text", "text": label}, "value": token, **extra}

    blocks = _text_blocks(text)
    if len(blocks) + 1 > MAX_BLOCKS:
        return None
    return [*blocks, {"type": "actions", "block_id": "order", "elements": [button("확인", CONFIRM_ID, style="primary"), button("취소", CANCEL_ID)]}]


def _send(dm: Dm, text: str, blocks: list[dict] | None = None) -> None:
    """답장 한 통. 실패해도 예외를 밖으로 내지 않는다(DB 는 이미 커밋됨). 슬랙 오류는 짧은 error 코드만 남긴다."""
    try:
        slack_client.get_client().post_message(dm.channel, text, dm.thread_ts, blocks)
    except SlackApiError as exc:
        log.warning("slack_event outcome=%s event_id=%s error=%s", "SEND_FAILED", dm.event_id, exc.response.get("error"))
    except Exception as exc:  # noqa: BLE001  연결 실패·토큰 없음 등 무엇이든 웹에 영향을 주면 안 된다
        log.warning("slack_event outcome=%s event_id=%s error=%s", "SEND_FAILED", dm.event_id, type(exc).__name__)


def _outcome(code: str, event_id: str | None) -> None:
    log.info("slack_event outcome=%s event_id=%s", code, event_id)


def _process(db: Session, dm: Dm, at: datetime) -> tuple[str, str | None] | None:
    """DM 한 통을 처리하고 보낼 (글, 버튼 토큰)(없으면 None)을 돌려준다. DB 확정은 여기서 끝낸다."""
    link = db.scalar(select(SlackLink).where(
        SlackLink.slack_team_id == dm.team_id, SlackLink.slack_user_id == dm.user))  # 연결된 행만 이 칸이 차 있다
    asks_link = LINK_PATTERN.fullmatch(dm.text.strip())
    if link is not None:  # 연결된 사용자: 회사를 알므로 DB 로 중복을 막는다
        if not idempotency.claim(db, link.company_id, EVENT_ENDPOINT, dm.event_id):
            db.rollback()
            _outcome("DUPLICATE", dm.event_id)
            return None
        db.commit()  # 키 확정: 이 뒤로 같은 event_id 는 건너뛴다
        word = dm.text.strip()
        if asks_link:
            _outcome("ALREADY_LINKED", dm.event_id)
            return ALREADY_LINKED, None
        if word in ("취소", "도움말"):  # 서버가 직접 답한다 (LLM 을 부르지 않는다)
            _outcome("CANCEL_IDLE" if word == "취소" else "HELP", dm.event_id)
            return (CANCEL_IDLE if word == "취소" else HELP), None
        if _rate_limited(link.company_id, link.user_id, at):  # LLM 을 부르기 전에 사람별로 막는다
            log.info("slack_order action=PROPOSE outcome=RATE_LIMITED company_id=%s user_id=%s", link.company_id, link.user_id)
            return RATE_LIMITED, None
        reply = chat_order.propose(db, link.company_id, link.user_id, dm.text, at.astimezone(SEOUL).date(), at)  # 회사·사용자는 연결 행의 값
        db.rollback()  # 읽기만 했다
        _outcome("ORDER_PROPOSED" if reply.token else "ORDER_NO_PROPOSAL", dm.event_id)
        return reply.text, reply.token
    if not _remember(dm.event_id, at):  # 연결 전 사용자: 메모리로 중복을 막는다 (틀린 코드가 두 번 세지지 않게)
        _outcome("DUPLICATE", dm.event_id)
        return None
    if asks_link is None:
        _outcome("NOT_LINKED", dm.event_id)
        return NOT_LINKED, None
    row = slack_link.redeem_code(db, dm.team_id, dm.user, asks_link.group(1), at)  # 성공·실패 사유는 redeem_code 가 감사 로그에 남긴다
    _outcome("LINK_OK" if row else "LINK_FAIL", dm.event_id)
    return (LINKED if row else slack_link.FAIL_MESSAGE), None


def handle_event(envelope: dict, at: datetime) -> None:
    """뒤에서 이벤트 하나를 처리한다. 어떤 실패도 밖으로 내지 않는다(웹 API·워커가 멈추지 않게)."""
    dm = parse_dm(envelope)
    if dm is None:
        _outcome("IGNORED", envelope.get("event_id"))
        return
    if not slack_link.enabled() or dm.team_id != settings.slack_team_id:  # 허용한 워크스페이스 하나만
        _outcome("WRONG_TEAM", dm.event_id)
        return
    if _was_seen(dm.event_id, at):  # 연결 전에 처리한 이벤트가 연결된 뒤 재전송된 경우도 여기서 막힌다
        _outcome("DUPLICATE", dm.event_id)
        return
    try:
        with SessionLocal() as db:  # 이 이벤트 전용 세션 (테스트는 SessionLocal 을 테스트 세션으로 바꿔 끼운다)
            result = _process(db, dm, at)
    except Exception as exc:  # noqa: BLE001  DB 오류 등. 세션은 with 가 닫으며 확정 안 된 작업을 버린다
        _forget(dm.event_id)
        log.warning("slack_event outcome=%s event_id=%s error=%s", "ERROR", dm.event_id, type(exc).__name__)
        return
    if result:
        text, token = result
        blocks = _order_blocks(text, token) if token else None
        if token and blocks is None:  # 요약이 너무 길어 다 보여 줄 수 없다: 버튼 없이 거절(토큰은 버려지고 아무것도 만들어지지 않는다)
            _outcome("SUMMARY_TOO_LONG", dm.event_id)
            text = MSG_SPLIT
        _send(dm, _escape(text), blocks)  # 슬랙 글에서 & < > 는 바꿔 보낸다


# ----- 버튼 (block_actions) -----
# 근거: Slack 공식 문서 docs.slack.dev "block_actions payload"(2026-11 확인) — 키 type, user.id, user.team_id, team.id, channel.id,
#       container.message_ts(또는 message.ts), actions[].action_id·value. HTTP 는 docs.slack.dev "Handling user interaction":
#       application/x-www-form-urlencoded 본문의 payload 칸이 JSON 이고 3초 안에 200 으로 받음을 알린다.
#       Socket Mode 는 같은 JSON 이 봉투 안에서 이미 풀린 dict(req.payload)로 온다. 키가 없거나 모양이 다르면 BAD_PAYLOAD 로 아무것도 하지 않는다.

@dataclass(frozen=True)
class Click:
    """누른 버튼 한 번에서 필요한 값만 꺼낸 것. 슬랙이 보낸 값은 누른 사람 찾기와 메시지 위치(channel·ts)에만 쓴다."""

    team_id: str
    user: str  # 누른 슬랙 사용자 id
    channel: str
    ts: str  # 버튼이 달린 메시지의 ts (chat.update 대상)
    action_id: str
    token: str


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def parse_click(payload: dict) -> Click | None:
    """block_actions 에서 값을 꺼낸다. 키가 없거나 글자가 아니면 None(BAD_PAYLOAD)."""
    user, team, channel = _dict(payload.get("user")), _dict(payload.get("team")), _dict(payload.get("channel"))
    ts = _dict(payload.get("container")).get("message_ts") or _dict(payload.get("message")).get("ts")
    actions = payload.get("actions")
    action = _dict(actions[0]) if isinstance(actions, list) and actions else {}
    fields = (team.get("id") or user.get("team_id"), user.get("id"), channel.get("id"), ts, action.get("action_id"), action.get("value"))
    if not all(isinstance(f, str) and f for f in fields):
        return None
    return Click(*fields)


def _action_outcome(code: str, error: str | None = None) -> None:
    log.info("slack_action outcome=%s error=%s", code, error)


def _tell(click: Click, text: str) -> None:
    """누른 사람에게만 보이는 안내. 실패해도 밖으로 내지 않는다."""
    try:
        slack_client.get_client().post_ephemeral(click.channel, click.user, _escape(text))
    except Exception as exc:  # noqa: BLE001
        _action_outcome("EPHEMERAL_FAILED", exc.response.get("error") if isinstance(exc, SlackApiError) else type(exc).__name__)


def _replace_buttons(click: Click, text: str) -> None:
    """버튼 메시지를 결과 문구로 바꾼다(보조 방어선). 실패하면 사유만 남기고, 결과는 그대로 두며 누른 사람에게 결과를 따로 알린다."""
    try:
        slack_client.get_client().update_message(click.channel, click.ts, _escape(text), _text_blocks(text))
    except Exception as exc:  # noqa: BLE001
        _action_outcome("UPDATE_FAILED", exc.response.get("error") if isinstance(exc, SlackApiError) else type(exc).__name__)
        _tell(click, text)


def _result_text(reply: chat_order.Reply) -> str:
    """결과 문구. 발주서를 만들었고 웹 주소가 https 일 때만 목록 링크를 붙인다. 사용자가 쓴 글은 되풀이하지 않는다."""
    base = settings.app_base_url
    if reply.po_ids and base.startswith("https://"):
        return f"{reply.text}\n웹에서 보기: {base.rstrip('/')}{WEB_ORDERS_PATH}"
    return reply.text


def _handle_action(payload: dict, at: datetime) -> None:
    if not isinstance(payload, dict) or payload.get("type") != "block_actions":
        _action_outcome("IGNORED")
        return
    click = parse_click(payload)
    if click is None:
        _action_outcome("BAD_PAYLOAD")  # 모양이 다르면 아무것도 하지 않는다
        return
    if click.action_id not in (CONFIRM_ID, CANCEL_ID):
        _action_outcome("IGNORED")
        return
    if not slack_link.enabled() or click.team_id != settings.slack_team_id:  # 허용한 워크스페이스 하나만
        _action_outcome("WRONG_TEAM")
        return
    linked = True
    try:
        with SessionLocal() as db:
            link = db.scalar(select(SlackLink).where(
                SlackLink.slack_team_id == click.team_id, SlackLink.slack_user_id == click.user))  # 누른 사람 = 이 행의 사용자
            if link is None:
                linked, reply = False, chat_order.Reply(chat_order.MSG_NOT_LINKED, outcome="NOT_LINKED")
            elif click.action_id == CONFIRM_ID:
                reply = chat_order.confirm(db, link.company_id, link.user_id, click.token, at.astimezone(SEOUL).date(), at)
            else:
                reply = chat_order.cancel(db, link.company_id, link.user_id, click.token)
    except Exception as exc:  # noqa: BLE001  chat_order 는 예상 못 한 오류도 rollback 한 뒤 올린다
        _action_outcome("ERROR", type(exc).__name__)
        _tell(click, ACTION_ERROR)
        return
    # 다른 사람이 눌렀거나 이미 처리된 경우: 원래 메시지(진짜 결과가 적혔을 수 있다)는 두고 누른 사람에게만 알린다. 문구가 아니라 사유 코드로 가른다
    if not linked or reply.outcome in ("WRONG_USER", "ALREADY_DONE"):
        _action_outcome("NOT_LINKED" if not linked else "NOTICE_ONLY")
        _tell(click, reply.text)
        return
    _action_outcome("CONFIRMED" if reply.po_ids else "ANSWERED")
    _replace_buttons(click, _result_text(reply))


def handle_action(payload: dict, at: datetime) -> None:
    """뒤에서 버튼 한 번을 처리한다. 어떤 실패도 밖으로 내지 않는다."""
    try:
        _handle_action(payload, at)
    except Exception as exc:  # noqa: BLE001  파싱·슬랙 호출 등 어디서든. 워커·웹이 멈추면 안 된다
        _action_outcome("ERROR", type(exc).__name__)
