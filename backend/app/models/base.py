from datetime import datetime  # 시각 칸의 파이썬 타입

from sqlalchemy import DateTime, ForeignKey, func  # 시간대 포함 시각, 외래키, DB 함수(now 등)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # 모델 정의 도구


class Base(DeclarativeBase):
    """모든 표 모델의 부모. Alembic은 Base.metadata를 보고 표 구조를 비교한다."""


class TimestampMixin:
    """모든 표에 공통인 칸: id, 만든 시각, 고친 시각."""

    id: Mapped[int] = mapped_column(primary_key=True)  # 행 번호 (자동 증가)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()  # 시간대 포함 시각, 행을 넣을 때 DB가 현재 시각을 채운다
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()  # 행을 고칠 때마다 현재 시각으로 바뀐다
    )


class CompanyMixin(TimestampMixin):
    """companies를 뺀 모든 표: 공통 칸 + 소속 회사(R1 회사 분리)."""

    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)  # 소속 회사, 회사별 조회가 많아 인덱스를 둔다
