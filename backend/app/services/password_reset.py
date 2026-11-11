"""비밀번호 재설정(#170): 이메일 링크 → 한 번만 쓰는 토큰(해시 저장, 30분) → 새 비밀번호."""

import logging  # 메일 발송 실패를 서버 로그에 남긴다
import secrets  # 추측할 수 없는 무작위 토큰
from datetime import datetime, timedelta  # 만료 시각 계산
from email.message import EmailMessage  # 보낼 메일 한 통

from sqlalchemy import select  # SELECT 문 만들기
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth import lockout  # 현재 시각 함수, 로그인 잠금 해제
from app.auth.security import (  # 비밀번호·토큰 도구
    hash_password,
    hash_reset_token,
    validate_password,
)
from app.config import settings  # APP_BASE_URL, SMTP_FROM
from app.errors import AppError  # 공통 오류
from app.models import User  # 사용자 표
from app.services import po_mail  # 메일 발송(deliver) 재사용 (#158)

RESET_MINUTES = 30  # 링크 유효 시간 (임시 확정)
SENT_MESSAGE = "가입된 이메일이라면 재설정 메일을 보냈습니다."  # 이메일이 있든 없든 같은 문장
INVALID_MESSAGE = "링크가 만료되었거나 이미 사용되었습니다. 다시 요청해 주세요."  # 틀림·만료·사용됨을 구분하지 않는다
log = logging.getLogger(__name__)  # 이 파일의 로그


def ensure_ready() -> None:
    """링크·메일 설정이 없으면 503. 이메일과 무관한 서버 설정 문제라 존재 여부가 드러나지 않는다."""
    if not (settings.app_base_url and settings.smtp_host and settings.smtp_from):
        raise AppError(503, "MAIL_NOT_CONFIGURED", "지금은 재설정 메일을 보낼 수 없습니다. 관리자에게 문의해 주세요.")


def issue_token(db: Session, email: str) -> tuple[str, str] | None:
    """가입된 활성 이메일이면 새 토큰을 만들어 해시만 저장하고 (이메일, 원본 토큰)을 돌려준다. 이전 링크는 덮어써 무효가 된다."""
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))  # 활성 사용자만
    if user is None:  # 없는 이메일이면 아무것도 하지 않는다 (응답은 똑같다)
        return None
    token = secrets.token_urlsafe(32)  # 원본 토큰 (메일에만 담긴다)
    user.reset_token_hash = hash_reset_token(token)  # 해시만 저장 (이전 링크는 여기서 무효)
    user.reset_expires_at = lockout.now() + timedelta(minutes=RESET_MINUTES)  # 30분 뒤 만료
    db.commit()  # 확정
    return user.email, token


def send_reset_mail(email: str, token: str) -> None:
    """재설정 링크 메일 한 통을 보낸다. 실패해도 응답은 이미 나갔으니 로그만 남긴다(원문 오류·링크는 남기지 않는다)."""
    msg = EmailMessage()
    msg["Subject"] = "[Cloud SCM] 비밀번호 재설정 안내"
    msg["From"] = settings.smtp_from  # 시스템 주소
    msg["To"] = email  # 요청한 이메일
    link = f"{settings.app_base_url.rstrip('/')}/reset-password?token={token}"  # 앞부분은 환경 변수
    msg.set_content(
        f"비밀번호를 다시 정하려면 아래 링크를 열어 주세요. 링크는 {RESET_MINUTES}분 동안, 한 번만 쓸 수 있습니다.\n\n"
        f"{link}\n\n요청하지 않았다면 이 메일은 무시하셔도 됩니다."
    )
    try:
        po_mail.deliver(msg)  # 실제 발송 (테스트는 이 함수를 가짜로 바꾼다)
    except Exception as exc:  # noqa: BLE001  메일 서버 거부·연결 실패 등 무엇이든 응답에 영향을 주면 안 된다
        log.warning("재설정 메일 발송 실패: %s", type(exc).__name__)  # 종류만 남긴다


def confirm_reset(db: Session, token: str, new_password: str, at: datetime) -> None:
    """토큰이 맞고 안 만료됐으면 비밀번호를 바꾸고 링크를 비운다. 아니면 400."""
    user = db.scalar(select(User).where(User.reset_token_hash == hash_reset_token(token)))  # 해시로 찾는다
    if user is None or not user.is_active or user.reset_expires_at is None or user.reset_expires_at <= at:  # 없음·비활성·만료
        raise AppError(400, "INVALID_RESET_TOKEN", INVALID_MESSAGE)
    validate_password(new_password)  # 8자 미만이면 422 (링크는 그대로 남아 다시 시도할 수 있다)
    user.password_hash = hash_password(new_password)  # 해시만 저장 (옛 로그인 토큰은 지문이 달라져 무효)
    user.reset_token_hash = None  # 한 번만 쓸 수 있다
    user.reset_expires_at = None
    user.must_change_password = False  # 직접 정한 비밀번호이므로 변경 필요 표시 해제
    db.commit()  # 확정
    lockout.record_success(user.email)  # 이메일 소유를 확인했으니 로그인 잠금도 푼다
