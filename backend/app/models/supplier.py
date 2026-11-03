from sqlalchemy import CheckConstraint, UniqueConstraint, true  # CHECK, 유일 제약, DB의 참 값
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class Supplier(CompanyMixin, Base):
    """공급업체: 발주 대상, 리드타임을 가진다."""

    __tablename__ = "suppliers"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_suppliers_company_name"),  # 회사 안에서 업체명 중복 불가
        CheckConstraint("lead_time_days >= 0", name="ck_suppliers_lead_time"),  # 리드타임은 0 이상
    )

    name: Mapped[str]  # 업체명
    contact_name: Mapped[str | None]  # 담당자 (| None 은 비워 둘 수 있다는 뜻)
    phone: Mapped[str | None]  # 연락처
    email: Mapped[str | None]  # 이메일
    memo: Mapped[str | None]  # 메모
    lead_time_days: Mapped[int]  # 발주해서 받을 때까지 걸리는 일수
    is_active: Mapped[bool] = mapped_column(server_default=true())  # 기본 참, 삭제 대신 비활성
