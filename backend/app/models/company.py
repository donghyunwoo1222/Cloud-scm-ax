from sqlalchemy import CheckConstraint  # CHECK 제약
from sqlalchemy.orm import Mapped  # 칸 타입 표시

from app.models.base import Base, TimestampMixin  # 공통 부모와 공통 칸


class Company(TimestampMixin, Base):
    """회사: 모든 데이터의 울타리(R1)."""

    __tablename__ = "companies"  # DB 표 이름
    __table_args__ = (CheckConstraint("business_number ~ '^[0-9]{10}$'", name="ck_companies_business_number"),)  # 숫자 10자리만

    name: Mapped[str]  # 회사명 (Mapped[str]은 NOT NULL = 필수)
    business_number: Mapped[str | None]  # 사업자등록번호 (숫자 10자리만 저장, 하이픈은 입력 때 지운다)
    representative: Mapped[str | None]  # 대표자
    address: Mapped[str | None]  # 주소
    phone: Mapped[str | None]  # 대표 연락처
