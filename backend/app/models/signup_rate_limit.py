"""회사 생성 전 IP별 가입 횟수를 보관하는 운영 테이블."""

from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SignupRateLimit(Base):
    __tablename__ = "signup_rate_limits"

    ip_hash: Mapped[bytes] = mapped_column(primary_key=True)  # 비밀키로 만든 HMAC
    attempts: Mapped[int]  # 이 시간 창에서 허용한 시도 수
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
