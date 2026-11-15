"""슬랙 연결(#197): 웹에서 6자리 코드 발급 → 슬랙 DM 으로 "연결 123456" → 코드 주인의 회사·사용자에 슬랙 계정을 잇는다.

회사 분리: company_id 는 언제나 slack_links 행(= 코드를 발급한 로그인 사용자)에서만 가져온다. 슬랙 메시지의 값은 쓰지 않는다.
코드는 원문을 저장하지 않고 HMAC 해시만 둔다. 슬랙 DM 에서는 누가 냈는지 모르므로 사용자 id 없이 서버 비밀키로만 해시해 행을 찾는다.
이 파일은 슬랙을 호출하지 않는다. DM 을 받아 redeem_code 를 부르는 쪽은 PR 3(받는 문)이다.
"""

import hashlib  # SHA-256
import hmac  # 비밀키를 섞은 해시
import logging  # 감사 이력 한 줄 (코드 원문·해시는 남기지 않는다)
import re  # 6자리 숫자 검사
import secrets  # 추측할 수 없는 코드
import threading  # 실패 기록을 동시에 만져도 꼬이지 않게
from datetime import UTC, datetime, timedelta  # 만료·잠금 시간 계산

from sqlalchemy import delete, select  # DELETE·SELECT 문
from sqlalchemy.exc import IntegrityError  # 고유 인덱스 위반
from sqlalchemy.orm import Session  # DB 세션 타입

from app.config import settings  # SLACK_ENABLED·SLACK_TEAM_ID·SECRET_KEY
from app.errors import AppError  # 공통 오류
from app.models import SlackLink, User  # 슬랙 연결 표, 사용자 표

CODE_MINUTES = 10  # 코드 유효 시간
MAX_FAILURES = 5  # 같은 슬랙 사용자가 이만큼 틀리면 잠근다 (로그인 잠금 #168 과 같은 숫자)
LOCK_MINUTES = 15  # 잠금 시간. 마지막 실패 후 이만큼 지나면 횟수도 잊는다
MAX_KEYS = 10000  # 메모리 보호: 기록이 이보다 많으면 오래된 것부터 지운다
FAIL_MESSAGE = "코드가 맞지 않거나 만료됐어요."  # 실패는 이유와 상관없이 같은 문장 (사유는 로그에만)

log = logging.getLogger(__name__)

# shortcut: 실패 횟수·잠금을 서버 메모리에 둔다. 재시작하면 초기화되고, 서버가 여러 대면 대수만큼 시도가 늘어난다.
#           잠금이 풀리면 다시 5번 시도할 수 있어 하루 최대 약 480번(15분마다 5번)까지 누적된다(대기 코드 10개면 하루 약 0.5%).
#           실제 사용자가 늘거나 서버를 늘리면 DB 표 + 하루 누적 한도로 옮긴다(#43 배포 때 재검토).
_failures: dict[tuple[str, str], tuple[int, datetime, datetime | None]] = {}  # (팀, 슬랙 사용자) → (실패 수, 마지막 실패, 잠금 해제 시각)
_lock = threading.Lock()


def now() -> datetime:
    return datetime.now(UTC)  # 테스트가 바꿔 끼워 시간을 옮긴다


def reset() -> None:
    with _lock:
        _failures.clear()  # 테스트용: 실패 기록 삭제


def enabled() -> bool:
    """스위치가 켜져 있고 허용할 워크스페이스가 정해져 있어야 켜짐."""
    return settings.slack_enabled and bool(settings.slack_team_id)


def hash_code(code: str) -> str:
    """연결 코드 해시. 6자리는 100만 가지뿐이라 비밀키를 섞어(HMAC) DB 가 새도 키 없이는 풀 수 없게 한다. 용도 접두어로 다른 해시와 섞이지 않게 한다."""
    return hmac.new(settings.secret_key.encode(), f"slack-link:{code}".encode(), hashlib.sha256).hexdigest()


def _audit(action: str, outcome: str, company_id: int | None = None, user_id: int | None = None) -> None:
    """감사 이력 한 줄. 코드 원문·해시·슬랙 id 는 남기지 않는다."""
    log.info("slack_link action=%s outcome=%s company_id=%s user_id=%s", action, outcome, company_id, user_id)


def status(db: Session, user: User) -> dict:
    """GET /slack/link: 내 연결 상태. NONE(없음) / PENDING(코드 발급, 연결 전) / LINKED(연결됨)."""
    row = db.scalar(select(SlackLink).where(SlackLink.company_id == user.company_id, SlackLink.user_id == user.id))
    state = "NONE" if row is None else ("LINKED" if row.linked_at else "PENDING")
    return {
        "enabled": enabled(),
        "status": state,
        "code_expires_at": row.link_code_expires_at if state == "PENDING" else None,  # 만료된 코드도 시각은 보여 준다(화면이 "만료" 표시)
        "slack_user_id": row.slack_user_id if row else None,
        "linked_at": row.linked_at if row else None,
    }


def issue_code(db: Session, user: User, at: datetime) -> tuple[str, datetime]:
    """POST /slack/link/code: 새 코드를 만들어 해시만 저장하고 (원문, 만료 시각)을 돌려준다. 이전 코드는 덮어써 무효."""
    if not enabled():
        raise AppError(503, "SLACK_DISABLED", "지금은 슬랙 연동을 쓸 수 없습니다.")
    db.get(User, user.id, with_for_update=True)  # 사용자 행 잠금: 같은 사람이 동시에 두 번 눌러도 한 줄로 선다
    row = db.scalar(select(SlackLink).where(SlackLink.company_id == user.company_id, SlackLink.user_id == user.id))
    if row is not None and row.linked_at is not None:  # 연결된 상태에서 새 코드를 주면 다른 슬랙 계정으로 몰래 옮길 수 있다
        raise AppError(409, "SLACK_ALREADY_LINKED", "이미 슬랙과 연결되어 있습니다. 먼저 연결을 해제해 주세요.")
    for _ in range(5):  # 살아 있는 다른 코드와 겹치면 다시 뽑는다 (100만 가지라 거의 한 번에 끝난다)
        code = f"{secrets.randbelow(10**6):06d}"  # 000000~999999
        digest = hash_code(code)
        if db.scalar(select(SlackLink.id).where(SlackLink.link_code_hash == digest)) is None:
            break
    else:
        raise AppError(503, "SLACK_CODE_UNAVAILABLE", "지금은 연결 코드를 만들 수 없습니다. 잠시 후 다시 시도해 주세요.")
    if row is None:
        row = SlackLink(company_id=user.company_id, user_id=user.id)  # 회사·사용자는 로그인 토큰에서 온 값만
        db.add(row)
    expires_at = at + timedelta(minutes=CODE_MINUTES)
    row.link_code_hash, row.link_code_expires_at = digest, expires_at
    db.commit()  # 확정 (잠금도 풀린다). 다른 사용자와 같은 순간 같은 코드를 뽑으면 고유 인덱스가 막는다(100만분의 1, 다시 누르면 된다)
    _audit("ISSUE", "OK", user.company_id, user.id)
    return code, expires_at


def unlink(db: Session, user: User) -> None:
    """POST /slack/link/unlink: 내 연결(또는 대기 중인 코드)을 지운다. 슬랙이 꺼져 있어도 해제는 된다. 없으면 아무 일도 없다."""
    db.execute(delete(SlackLink).where(SlackLink.company_id == user.company_id, SlackLink.user_id == user.id))
    db.commit()
    _audit("UNLINK", "OK", user.company_id, user.id)


def _locked(key: tuple[str, str], at: datetime) -> bool:
    with _lock:
        record = _failures.get(key)
        return record is not None and record[2] is not None and at < record[2]


def _fail(key: tuple[str, str], at: datetime) -> None:
    """실패 1번 기록. 마지막 실패 후 15분이 지났으면 새로 센다. 5번째면 15분 잠근다."""
    with _lock:
        count, last, _ = _failures.get(key, (0, at, None))
        if at - last >= timedelta(minutes=LOCK_MINUTES):
            count = 0
        count += 1
        _failures[key] = (count, at, at + timedelta(minutes=LOCK_MINUTES) if count >= MAX_FAILURES else None)
        if len(_failures) > MAX_KEYS:  # 없는 사용자 id 를 마구 보내 메모리를 채우는 공격 방어
            for old in sorted(_failures, key=lambda k: _failures[k][1])[: len(_failures) - MAX_KEYS]:
                del _failures[old]


def redeem_code(db: Session, team_id: str, slack_user_id: str, code: str, at: datetime) -> SlackLink | None:
    """슬랙 DM "연결 123456" 처리. 성공하면 연결된 행, 실패하면 None(호출하는 쪽은 FAIL_MESSAGE 하나만 보여 준다).

    실패 사유(WRONG_TEAM·LOCKED·ALREADY_LINKED·NOT_FOUND·EXPIRED)는 로그에만 남긴다. 다 쓴 코드는 해시를 비우므로
    다시 쓰면 NOT_FOUND 다. 코드 행을 잠그고 바꾸므로 같은 코드를 동시에 두 번 내도 한 번만 성공한다.
    """
    if not enabled() or team_id != settings.slack_team_id:  # 허용한 워크스페이스 하나만
        _audit("REDEEM", "WRONG_TEAM")
        return None
    key = (team_id, slack_user_id)
    if _locked(key, at):  # 잠금 중에는 맞는 코드여도 보지 않는다
        _audit("REDEEM", "LOCKED")
        return None
    if db.scalar(select(SlackLink.id).where(SlackLink.slack_team_id == team_id, SlackLink.slack_user_id == slack_user_id)):
        _audit("REDEEM", "ALREADY_LINKED")  # 이 슬랙 계정은 이미 누군가와 연결됨 (코드는 보지 않아 시도로 세지 않는다)
        return None
    row = None
    if re.fullmatch(r"\d{6}", code):  # 모양이 틀리면 찾지 않고 실패로 센다
        row = db.scalar(select(SlackLink).where(SlackLink.link_code_hash == hash_code(code)).with_for_update())  # 행 잠금
    if row is None or row.link_code_expires_at <= at:
        _fail(key, at)
        owner = (row.company_id, row.user_id) if row else (None, None)  # rollback 전에 읽어 둔다
        db.rollback()  # 잠금 풀기
        _audit("REDEEM", "NOT_FOUND" if row is None else "EXPIRED", *owner)
        return None
    company_id, user_id = row.company_id, row.user_id
    row.slack_team_id, row.slack_user_id, row.linked_at = team_id, slack_user_id, at
    row.link_code_hash = row.link_code_expires_at = None  # 한 번 쓰면 폐기
    try:
        db.commit()
    except IntegrityError:  # 같은 슬랙 계정이 다른 코드로 동시에 연결한 경우: 고유 인덱스가 하나만 남긴다
        db.rollback()
        _audit("REDEEM", "ALREADY_LINKED")
        return None
    _audit("REDEEM", "OK", company_id, user_id)
    return row
