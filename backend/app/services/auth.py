"""회사 가입과 로그인 확인 (업무 규칙 층)."""

from sqlalchemy import select  # SELECT 문 만들기
from sqlalchemy.exc import IntegrityError  # 제약 위반 오류
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth.security import hash_password, validate_password, verify_password  # 비밀번호 도구
from app.errors import AppError  # 공통 오류
from app.models import Company, User  # 회사, 사용자 표
from app.schemas.auth import CompanySignup  # 가입 요청 모양

LOGIN_FAILED = "이메일 또는 비밀번호가 올바르지 않습니다."  # 어느 쪽이 틀렸는지 알려주지 않는다


def create_company(db: Session, data: CompanySignup) -> User:
    """회사와 첫 관리자(ADMIN)를 한 트랜잭션으로 만든다. 둘 중 하나라도 실패하면 둘 다 저장 안 됨."""
    validate_password(data.password)  # 8자 미만이면 422
    company = Company(name=data.company_name)  # 회사
    db.add(company)  # 세션에 올림
    db.flush()  # INSERT 실행 → company.id 가 생긴다 (아직 확정 아님)
    admin = User(
        company_id=company.id,  # 방금 만든 회사 소속
        name=data.admin_name,  # 이름
        email=data.email,  # 소문자로 정리된 이메일
        password_hash=hash_password(data.password),  # 원문 대신 해시만 저장
        role="ADMIN",  # 첫 계정은 관리자
    )
    db.add(admin)  # 세션에 올림
    commit_new_user(db)  # 회사 + 관리자를 함께 확정 (이메일 중복이면 둘 다 취소 후 409)
    return admin  # 만든 관리자


def commit_new_user(db: Session) -> None:
    """새 사용자를 확정한다. 이메일 중복이면 되돌리고 409 EMAIL_TAKEN. 회사 가입(#22)·직원 생성(#24)이 함께 쓴다."""
    try:
        db.commit()  # 확정
    except IntegrityError as e:  # 제약 위반이면
        db.rollback()  # 이번 트랜잭션의 INSERT 를 모두 취소
        if getattr(e.orig.diag, "constraint_name", None) == "users_email_key":  # 이메일 유일 제약이면
            raise AppError(409, "EMAIL_TAKEN", "이미 사용 중인 이메일입니다.") from None
        raise  # 그 밖의 위반은 예상 밖이라 그대로 올린다 (500)


def authenticate(db: Session, email: str, password: str) -> User:
    """이메일·비밀번호가 맞고 활성 사용자면 돌려준다. 아니면 이유와 상관없이 같은 401."""
    user = db.scalar(select(User).where(User.email == email))  # 이메일로 사용자 찾기 (없으면 None)
    password_ok = verify_password(password, user.password_hash if user else None)  # 없어도 같은 시간만큼 검사
    if user is None or not password_ok or not user.is_active:  # 없음 / 틀림 / 비활성
        raise AppError(401, "UNAUTHENTICATED", LOGIN_FAILED)  # 세 경우 모두 같은 응답
    return user
