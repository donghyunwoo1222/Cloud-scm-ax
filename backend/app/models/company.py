from sqlalchemy.orm import Mapped  # 칸 타입 표시

from app.models.base import Base, TimestampMixin  # 공통 부모와 공통 칸


class Company(TimestampMixin, Base):
    """회사: 모든 데이터의 울타리(R1)."""

    __tablename__ = "companies"  # DB 표 이름

    name: Mapped[str]  # 회사명 (Mapped[str]은 NOT NULL = 필수)
