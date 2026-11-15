"""슬랙에서 오는 이벤트를 받는 어댑터 (#197 PR 3). 슬랙 모양을 해석하고, 업무 판단은 서비스(redeem_code 등)에 맡긴다.

흐름: 받는 쪽(HTTP 경로·Socket 워커)이 먼저 "받았음"을 보내고 → 뒤에서 handle_event 가 처리한다.
슬랙은 3초 안에 답이 없으면 같은 이벤트를 최대 3번 다시 보내므로(바로·1분·5분) event_id 로 한 번만 처리한다.
  - 연결된 사용자: idempotency_keys(회사는 slack_links 행에서)에 event_id 를 먼저 잡는다.
  - 연결 전 사용자: 회사를 모르므로 서버 메모리의 최근 event_id 목록으로 건너뛴다.
회사 분리: company_id 는 언제나 slack_links 행에서만 가져온다. 슬랙 본문의 값으로 회사를 정하지 않는다.
로그: 사유 코드와 event_id 만 남긴다. 메시지 원문·연결 코드·토큰·슬랙 사용자 id 는 남기지 않는다.
"""

import logging  # 사유 코드 한 줄
import re  # "연결 123456" 모양
import threading  # 최근 event_id 목록을 여러 스레드가 함께 만진다
from collections import OrderedDict  # 넣은 순서대로 오래된 것부터 지우기
from collections.abc import Mapping  # 요청 헤더 타입
from dataclasses import dataclass  # DM 한 통의 필요한 값만
from datetime import datetime, timedelta  # 처리 시각, 메모리 만료

from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답 (error 코드만 남긴다)
from slack_sdk.signature import SignatureVerifier  # 서명 검증 (5분 시각 검사 + 상수 시간 비교)
from sqlalchemy import select  # 연결 행 조회
from sqlalchemy.orm import Session  # DB 세션 타입

from app.config import settings  # SLACK_TEAM_ID·SLACK_SIGNING_SECRET
from app.db import SessionLocal  # 뒤 작업 전용 세션 (요청 세션은 응답 뒤 이미 닫혀 있다)
from app.models import SlackLink  # 슬랙 연결 표
from app.services import (  # 중복 막기, 메시지 보내기, 연결 코드
    idempotency,
    slack_client,
    slack_link,
)

log = logging.getLogger(__name__)

EVENT_ENDPOINT = "slack:event"  # idempotency_keys 의 endpoint 칸 (웹 경로와 겹치지 않는 이름)
LINK_PATTERN = re.compile(r"연결\s*(\S+)")  # "연결 123456" (코드 모양 검사는 redeem_code 가 한다)
LINKED = "연결됐어요."
ALREADY_LINKED = "이미 연결돼 있어요."
NOT_LINKED = "먼저 웹에서 연결 코드를 받아 연결해 주세요."
NOT_READY = "아직 준비 중이에요."  # 연결된 사용자의 다른 메시지 (해석은 PR 5)

SEEN_MAX = 1000  # 메모리에 기억할 최근 event_id 수
SEEN_MINUTES = 10  # 슬랙 재전송은 5분 뒤가 마지막이라 10분이면 덮인다

# shortcut: 연결 전 사용자의 event_id 는 서버 메모리에만 둔다. 재시작하면 잊고, 프로세스가 여러 개면 서로 모른다.
#           재전송이 다른 프로세스로 가면 틀린 코드가 한 번 더 셀 수 있다. 서버를 늘릴 때(#43) DB 로 옮길지 정한다.
_seen: OrderedDict[str, datetime] = OrderedDict()  # event_id → 처음 본 시각
_seen_lock = threading.Lock()


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


def _send(dm: Dm, text: str) -> None:
    """답장 한 통. 실패해도 예외를 밖으로 내지 않는다(DB 는 이미 커밋됨). 슬랙 오류는 짧은 error 코드만 남긴다."""
    try:
        slack_client.get_client().post_message(dm.channel, text, dm.thread_ts)
    except SlackApiError as exc:
        log.warning("slack_event outcome=%s event_id=%s error=%s", "SEND_FAILED", dm.event_id, exc.response.get("error"))
    except Exception as exc:  # noqa: BLE001  연결 실패·토큰 없음 등 무엇이든 웹에 영향을 주면 안 된다
        log.warning("slack_event outcome=%s event_id=%s error=%s", "SEND_FAILED", dm.event_id, type(exc).__name__)


def _outcome(code: str, event_id: str | None) -> None:
    log.info("slack_event outcome=%s event_id=%s", code, event_id)


def _process(db: Session, dm: Dm, at: datetime) -> str | None:
    """DM 한 통을 처리하고 보낼 답장(없으면 None)을 돌려준다. DB 확정은 여기서 끝낸다."""
    link = db.scalar(select(SlackLink).where(
        SlackLink.slack_team_id == dm.team_id, SlackLink.slack_user_id == dm.user))  # 연결된 행만 이 칸이 차 있다
    asks_link = LINK_PATTERN.fullmatch(dm.text.strip())
    if link is not None:  # 연결된 사용자: 회사를 알므로 DB 로 중복을 막는다
        if not idempotency.claim(db, link.company_id, EVENT_ENDPOINT, dm.event_id):
            db.rollback()
            _outcome("DUPLICATE", dm.event_id)
            return None
        db.commit()  # 키 확정: 이 뒤로 같은 event_id 는 건너뛴다
        _outcome("ALREADY_LINKED" if asks_link else "NOT_READY", dm.event_id)
        return ALREADY_LINKED if asks_link else NOT_READY
    if not _remember(dm.event_id, at):  # 연결 전 사용자: 메모리로 중복을 막는다 (틀린 코드가 두 번 세지지 않게)
        _outcome("DUPLICATE", dm.event_id)
        return None
    if asks_link is None:
        _outcome("NOT_LINKED", dm.event_id)
        return NOT_LINKED
    row = slack_link.redeem_code(db, dm.team_id, dm.user, asks_link.group(1), at)  # 성공·실패 사유는 redeem_code 가 감사 로그에 남긴다
    _outcome("LINK_OK" if row else "LINK_FAIL", dm.event_id)
    return LINKED if row else slack_link.FAIL_MESSAGE


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
            reply = _process(db, dm, at)
    except Exception as exc:  # noqa: BLE001  DB 오류 등. 세션은 with 가 닫으며 확정 안 된 작업을 버린다
        _forget(dm.event_id)
        log.warning("slack_event outcome=%s event_id=%s error=%s", "ERROR", dm.event_id, type(exc).__name__)
        return
    if reply:
        _send(dm, reply)
