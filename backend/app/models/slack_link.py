from datetime import datetime  # 시각 칸의 파이썬 타입

from sqlalchemy import (  # 제약·칸 타입·외래키·인덱스
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class SlackLink(CompanyMixin, Base):
    """슬랙 연결(#197): SCM 사용자 한 명 ↔ 슬랙 계정 하나. 업무 데이터가 아닌 기술용 기록이라 해제하면 행을 지운다.

    상태: 코드 발급(대기, link_code_hash 있음) → 연결됨(slack_user_id·linked_at 있음, 코드 칸은 비움).
    코드는 누가 냈는지 모르는 상태(슬랙 DM)에서 찾아야 해서 사용자 id 없이 서버 비밀키로만 해시한다.
    """

    __tablename__ = "slack_links"  # DB 표 이름
    __table_args__ = (
        # 연결됨 ⇔ 슬랙 사용자 id 와 연결 시각이 둘 다 있다 (하나만 있는 어중간한 행 금지)
        CheckConstraint("(slack_user_id IS NULL) = (linked_at IS NULL)", name="ck_slack_links_linked"),
        CheckConstraint("(slack_user_id IS NULL) = (slack_team_id IS NULL)", name="ck_slack_links_team"),
        # 살아 있는 코드는 전체에서 겹치지 않는다 (해시로 행을 찾으므로). 겹치면 서버가 새 코드를 다시 뽑는다
        Index("uq_slack_links_code_hash", "link_code_hash", unique=True, postgresql_where=text("link_code_hash IS NOT NULL")),
        # 슬랙 계정 하나는 SCM 사용자 한 명에게만 연결된다
        Index("uq_slack_links_slack_user", "slack_team_id", "slack_user_id", unique=True,
              postgresql_where=text("slack_user_id IS NOT NULL")),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)  # 연결할 SCM 사용자 (사용자당 한 행)
    link_code_hash: Mapped[str | None] = mapped_column(String(64))  # 연결 코드의 HMAC-SHA256 (원문은 저장하지 않는다). 쓰면 비운다
    link_code_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 코드 만료 = 발급 + 10분
    slack_team_id: Mapped[str | None] = mapped_column(String(32))  # 연결된 슬랙 워크스페이스 id (예: T0123ABCD)
    slack_user_id: Mapped[str | None] = mapped_column(String(32))  # 연결된 슬랙 사용자 id (예: U0123ABCD)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 연결된 시각
