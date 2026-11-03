"""직원 계정 관리 (F1). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1)."""

from sqlalchemy import func, select  # 개수 세기, SELECT 문
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth.security import hash_password, validate_password  # 비밀번호 규칙·해시 (#22)
from app.errors import AppError  # 공통 오류
from app.models import Company, User  # 회사, 사용자 표
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.users import UserCreate, UserUpdate  # 요청 모양
from app.services.auth import commit_new_user  # 이메일 중복 처리 포함 확정 (#22 와 공용)
from app.services.tenant import get_owned, scoped  # 회사 분리 도우미 (#23)


def list_users(company_id: int, db: Session, page: PageParams, include_inactive: bool) -> tuple[list, dict]:
    """우리 회사 직원 목록. 최신순, 기본은 활성 직원만."""
    stmt = scoped(company_id, User)  # 회사 조건이 붙은 시작점
    if not include_inactive:  # 비활성 포함을 요청하지 않았으면
        stmt = stmt.where(User.is_active.is_(True))  # 활성 직원만
    stmt = stmt.order_by(User.created_at.desc(), User.id.desc())  # 최신순 (같은 시각이면 나중에 만든 번호가 먼저)
    return paginate(db, stmt, page)  # 한 쪽 + meta


def create_user(company_id: int, db: Session, data: UserCreate) -> User:
    """관리자가 직원 계정을 만든다. 회사는 요청 본문이 아니라 로그인한 관리자의 회사."""
    validate_password(data.password)  # 8자 미만이면 422 (#22 와 같은 규칙)
    user = User(
        company_id=company_id,  # 토큰에서 온 회사
        name=data.name,  # 이름
        email=data.email,  # 소문자로 정리된 이메일
        password_hash=hash_password(data.password),  # 원문 대신 해시만 저장
        role=data.role,  # 역할
    )
    db.add(user)  # 세션에 올림
    commit_new_user(db)  # 확정, 이메일 중복이면 409 EMAIL_TAKEN
    return user


def update_user(company_id: int, db: Session, user_id: int, data: UserUpdate) -> User:
    """역할 변경·비활성·다시 활성. 마지막 활성 관리자를 잃게 되는 변경은 409 LAST_ADMIN."""
    user = get_owned(company_id, db, User, user_id)  # 다른 회사 직원이면 404
    loses_admin = user.role == "ADMIN" and user.is_active and (data.role == "STAFF" or data.is_active is False)  # 활성 관리자가 한 명 줄어드는 변경인가
    if loses_admin:
        db.get(Company, company_id, with_for_update=True)  # 회사 줄을 잠가, 두 관리자가 동시에 서로를 내려도 한 명씩 차례로 검사되게 한다
        active_admins = db.scalar(  # 지금 회사의 활성 관리자 수
            select(func.count()).select_from(
                scoped(company_id, User).where(User.role == "ADMIN", User.is_active.is_(True)).subquery()
            )
        )
        if active_admins <= 1:  # 이 사람이 마지막 활성 관리자면 (잠금은 요청이 끝나 세션이 닫힐 때 풀린다)
            raise AppError(409, "LAST_ADMIN", "회사에는 활성 관리자가 최소 1명 있어야 합니다.")
    if data.role is not None:  # 역할을 보냈으면
        user.role = data.role
    if data.is_active is not None:  # 활성 여부를 보냈으면
        user.is_active = data.is_active
    db.commit()  # 확정 (잠금도 여기서 풀린다)
    return user
