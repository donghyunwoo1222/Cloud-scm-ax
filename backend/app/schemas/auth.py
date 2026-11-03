"""회사 가입·로그인·내 정보의 요청·응답 모양."""

from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import AfterValidator, BaseModel, Field  # 검사 도구, 모양 정의


def normalize_email(value: str) -> str:
    """앞뒤 공백 제거 + 소문자. Admin@A.com 과 admin@a.com 을 같은 이메일로 본다."""
    value = value.strip().lower()  # 정리
    if "@" not in value:  # 최소한의 형식 검사 (정식 검사 라이브러리는 넣지 않았다)
        raise ValueError("이메일 형식이 아닙니다.")
    return value


Email = Annotated[str, AfterValidator(normalize_email)]  # 이메일 칸 공통 타입
Text = Annotated[str, Field(min_length=1, max_length=100)]  # 이름류: 1~100자


class CompanySignup(BaseModel):
    company_name: Text  # 회사명
    admin_name: Text  # 첫 관리자 이름
    email: Email  # 첫 관리자 로그인 이메일
    password: str  # 비밀번호 (길이 규칙은 auth/security.validate_password 한 곳에서 검사)


class LoginRequest(BaseModel):
    email: Email  # 로그인 이메일
    password: str  # 비밀번호


class CompanyOut(BaseModel):
    id: int  # 회사 번호
    name: str  # 회사명


class MeOut(BaseModel):
    """내 정보. 비밀번호 해시는 칸 자체가 없어 응답에 들어갈 수 없다."""

    name: str  # 이름
    email: str  # 이메일
    role: str  # ADMIN / STAFF
    company: CompanyOut  # 소속 회사
