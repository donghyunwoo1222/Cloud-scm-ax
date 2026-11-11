from sqlalchemy import CheckConstraint, false, true  # CHECK 제약, DB의 참(true) 값
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class User(CompanyMixin, Base):
    """사용자: 로그인 계정과 역할."""

    __tablename__ = "users"  # DB 표 이름
    __table_args__ = (
        CheckConstraint("role IN ('ADMIN', 'STAFF')", name="ck_users_role"),  # 역할은 두 값 중 하나만
    )

    name: Mapped[str]  # 사용자 이름
    email: Mapped[str] = mapped_column(unique=True)  # 로그인 ID, 전체 회사를 통틀어 중복 불가
    password_hash: Mapped[str]  # 비밀번호 해시 (원문은 저장하지 않는다)
    role: Mapped[str]  # ADMIN(관리자) 또는 STAFF(담당자)
    must_change_password: Mapped[bool] = mapped_column(server_default=false())  # 참이면 비밀번호를 바꾸기 전에는 다른 기능을 못 쓴다 (관리자가 만든 임시 비밀번호, #169)
    is_active: Mapped[bool] = mapped_column(server_default=true())  # 기본 참, 거짓이면 로그인 불가
