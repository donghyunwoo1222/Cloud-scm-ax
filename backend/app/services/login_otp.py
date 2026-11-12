"""관리자 로그인 메일 인증코드(#179): 비밀번호 통과 → 6자리 코드 메일 → 코드 확인 → 정식 로그인.

코드는 원문을 저장하지 않고 HMAC 해시만 users 칸에 둔다. 사용자당 살아 있는 코드는 하나이고 새로 보내면 덮어쓴다.
코드 확인·재발송·발급은 모두 사용자 행을 잠그고(SELECT … FOR UPDATE) 처리해, 같은 코드를 동시에 두 번 내도 한 번만 통과한다.
"""

import hmac  # 해시를 일정한 시간에 비교
import logging  # 메일 실패·비상 스위치 경고
import secrets  # 추측할 수 없는 코드
from datetime import datetime, timedelta  # 만료·간격 계산
from email.message import EmailMessage  # 보낼 메일 한 통

import jwt  # 임시 토큰 오류 종류
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth.security import (  # 코드 해시·임시 토큰
    decode_otp_token,
    hash_otp_code,
    password_fingerprint,
)
from app.clock import SEOUL  # 안내 문구의 날짜는 서울 기준
from app.config import settings  # 비상 스위치, 메일 설정
from app.errors import AppError  # 공통 오류
from app.models import User  # 사용자 표
from app.services import po_mail  # 메일 발송(deliver) 재사용

CODE_MINUTES = 10  # 코드 유효 시간
MAX_ATTEMPTS = 5  # 틀릴 수 있는 횟수. 5번째에 코드를 폐기하고 비밀번호부터 다시
RESEND_SECONDS = 60  # 코드 메일 최소 간격 (로그인·재발송 모두, 메일 폭탄 방지)
MAX_RESENDS = 3  # 로그인 한 번에 재발송할 수 있는 횟수
RESTART_MESSAGE = "인증 단계를 처음부터 다시 해 주세요. 이메일과 비밀번호로 다시 로그인해 주세요."
log = logging.getLogger(__name__)


def warn_if_disabled() -> None:
    """서버 시작 때 부른다. 비상 스위치가 꺼져 있으면 운영자가 알아차리도록 경고를 남긴다."""
    if not settings.admin_otp_enabled:
        log.warning("ADMIN_OTP_ENABLED=false: 관리자 로그인 메일 인증코드가 꺼져 있습니다 (비상 상태).")


def needs_otp(user: User, at: datetime) -> bool:
    """이번 로그인에 코드가 필요한가: 스위치 켜짐 + 관리자 + 유예가 없거나 끝남. 직원은 항상 아니다."""
    in_grace = user.otp_grace_until is not None and user.otp_grace_until > at
    return settings.admin_otp_enabled and user.role == "ADMIN" and not in_grace


def grace_notice(user: User, at: datetime) -> str | None:
    """유예 중인 관리자에게 매 로그인 보여 줄 안내. 코드·이메일은 넣지 않는다."""
    if not (settings.admin_otp_enabled and user.role == "ADMIN" and user.otp_grace_until and user.otp_grace_until > at):
        return None
    day = user.otp_grace_until.astimezone(SEOUL).date()  # 예) 2026-11-26
    return f"{day:%Y-%m-%d}부터 관리자 로그인에 메일 인증코드가 필요합니다. 이 계정 이메일로 메일을 받을 수 있는지 확인해 주세요."


def ensure_mail_ready() -> None:
    """메일 서버 설정이 없으면 503. 비밀번호가 맞은 관리자에게만 나오므로 계정 존재 여부와는 무관하다."""
    if not (settings.smtp_host and settings.smtp_from):
        raise AppError(503, "MAIL_NOT_CONFIGURED", "지금은 인증코드 메일을 보낼 수 없습니다. 서버 관리자에게 문의해 주세요.")


def lock_user(db: Session, user_id: int) -> User | None:
    """사용자 행을 잠그고 DB 의 최신 값으로 다시 읽는다 (요청이 끝날 때까지 다른 요청은 기다린다)."""
    return db.get(User, user_id, with_for_update=True, populate_existing=True)


def _new_code(db: Session, user: User, at: datetime) -> str:
    """새 코드를 만들어 해시만 저장하고 원문을 돌려준다(메일에만 담긴다). 이전 코드는 덮어써 무효."""
    code = f"{secrets.randbelow(10**6):06d}"  # 000000~999999
    user.otp_code_hash = hash_otp_code(user.id, code)
    user.otp_sent_at = at
    db.commit()  # 확정 (잠금도 풀린다)
    return code


def start(db: Session, user: User, at: datetime) -> str | None:
    """비밀번호 통과 직후. 새 코드 원문을 돌려주거나, 60초 안에 이미 보냈으면 None(새 메일 없음, 기존 코드 유지)."""
    user = lock_user(db, user.id)
    if user.otp_sent_at and at - user.otp_sent_at < timedelta(seconds=RESEND_SECONDS):
        db.commit()  # 잠금만 풀고 그대로 둔다
        return None
    user.otp_attempts = 0  # 새 로그인 = 새 코드, 틀린 횟수·재발송 횟수도 새로
    user.otp_resends = 0
    return _new_code(db, user, at)


def pending_user(db: Session, token: str | None) -> User:
    """otp_pending 쿠키의 임시 토큰으로 사용자를 찾아 행을 잠근다. 없음·위조·만료·비밀번호 변경이면 401."""
    try:
        payload = decode_otp_token(token or "")
    except jwt.InvalidTokenError:
        raise AppError(401, "UNAUTHENTICATED", RESTART_MESSAGE) from None
    user = lock_user(db, payload["user_id"])
    if user is None or not user.is_active or payload["pv"] != password_fingerprint(user.password_hash):
        raise AppError(401, "UNAUTHENTICATED", RESTART_MESSAGE)
    return user


def verify(db: Session, user: User, code: str, at: datetime) -> None:
    """잠근 사용자의 코드를 확인한다. 맞으면 코드를 비워 다시 못 쓰게 한다. 틀리면 횟수를 올리고 401."""
    if user.otp_code_hash is None or user.otp_attempts >= MAX_ATTEMPTS:  # 이미 썼거나 폐기됨
        raise AppError(401, "OTP_RESTART", RESTART_MESSAGE)
    if at - user.otp_sent_at >= timedelta(minutes=CODE_MINUTES):  # 10분 지남: 재발송으로 새 코드를 받으면 된다
        raise AppError(401, "OTP_EXPIRED", "인증코드가 만료되었습니다. 코드를 다시 받아 주세요.")
    if hmac.compare_digest(user.otp_code_hash, hash_otp_code(user.id, code)):
        user.otp_code_hash = None  # 한 번 쓰면 폐기
        user.otp_attempts = user.otp_resends = 0
        db.commit()
        return
    user.otp_attempts += 1
    left = MAX_ATTEMPTS - user.otp_attempts
    if left == 0:
        user.otp_code_hash = None  # 5번째 실패: 폐기
    db.commit()  # 틀린 횟수는 오류 응답이 나가도 남아야 한다
    if left == 0:
        raise AppError(401, "OTP_RESTART", RESTART_MESSAGE)
    raise AppError(401, "OTP_INVALID", f"인증코드가 올바르지 않습니다. {left}번 더 시도할 수 있습니다.", {"attempts_left": left})


def resend(db: Session, user: User, at: datetime) -> str:
    """잠근 사용자에게 새 코드를 만든다. 폐기된 코드·재발송 3번 초과·60초 안은 거절."""
    if user.otp_attempts >= MAX_ATTEMPTS or user.otp_sent_at is None:
        raise AppError(401, "OTP_RESTART", RESTART_MESSAGE)
    wait = RESEND_SECONDS - int((at - user.otp_sent_at).total_seconds())
    if wait > 0:
        raise AppError(429, "OTP_RESEND_WAIT", f"{wait}초 뒤에 다시 받을 수 있습니다.", {"retry_after": wait})
    if user.otp_resends >= MAX_RESENDS:
        raise AppError(429, "TOO_MANY_ATTEMPTS", f"재발송은 {MAX_RESENDS}번까지입니다. 이메일과 비밀번호로 다시 로그인해 주세요.")
    user.otp_resends += 1
    return _new_code(db, user, at)


def challenge_out(user: User, at: datetime, sent: bool) -> dict:
    """코드 단계 응답. 코드·토큰·이메일은 넣지 않는다."""
    elapsed = (at - user.otp_sent_at).total_seconds()
    return {
        "otp_required": True,
        "code_sent": sent,  # false = 60초 안에 다시 로그인해 새 메일을 보내지 않았다
        "message": ("인증코드를 이메일로 보냈습니다. 10분 안에 입력해 주세요." if sent
                    else "방금 보낸 인증코드가 아직 유효합니다. 받은 메일의 코드를 입력해 주세요."),
        "expires_in": max(0, int(CODE_MINUTES * 60 - elapsed)),  # 코드가 몇 초 더 유효한지
        "resend_after": max(0, int(RESEND_SECONDS - elapsed)),  # 몇 초 뒤 재발송 가능한지
    }


def send_code_mail(email: str, code: str) -> None:
    """코드 메일 한 통. 응답 뒤(BackgroundTasks)에 보내고, 실패하면 예외 종류만 로그에 남긴다(코드·주소는 남기지 않는다)."""
    msg = EmailMessage()
    msg["Subject"] = "[Cloud SCM] 관리자 로그인 인증코드"
    msg["From"] = settings.smtp_from
    msg["To"] = email
    msg.set_content(
        f"로그인 인증코드: {code}\n\n{CODE_MINUTES}분 동안 한 번만 쓸 수 있습니다.\n"
        "로그인을 시도하지 않았다면 비밀번호가 유출됐을 수 있으니 바로 비밀번호를 바꿔 주세요."
    )
    try:
        po_mail.deliver(msg)
    except Exception as exc:  # noqa: BLE001  메일 서버 거부·연결 실패 등 무엇이든 응답에 영향을 주면 안 된다
        log.warning("인증코드 메일 발송 실패: %s", type(exc).__name__)
