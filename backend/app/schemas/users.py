"""직원 계정 요청·응답 모양."""

from datetime import datetime  # 만든 시각
from typing import Literal  # 정해진 값 중 하나

from pydantic import BaseModel, ConfigDict  # 모양 정의, ORM 객체에서 읽기 설정

from app.schemas.auth import (  # 이메일 정리(공백 제거·소문자), 이름 길이 규칙 (#22 와 같은 것)
    Email,
    Text,
)

Role = Literal["ADMIN", "STAFF"]  # 역할은 둘 중 하나 (그 밖의 값은 422)


class UserCreate(BaseModel):
    name: Text  # 이름
    email: Email  # 로그인 이메일
    password: str  # 임시 비밀번호 (길이 규칙은 validate_password 한 곳에서)
    role: Role  # 역할 (기본값 없이 꼭 고르게 한다)


class UserUpdate(BaseModel):
    """바꿀 칸만 보낸다. 보내지 않은 칸은 그대로 둔다."""

    role: Role | None = None  # 역할 변경
    is_active: bool | None = None  # 비활성(false)·다시 활성(true)


class UserOut(BaseModel):
    """응답 모양. password_hash 칸이 아예 없어 실수로도 나갈 수 없다."""

    model_config = ConfigDict(from_attributes=True)  # User 객체에서 같은 이름의 칸을 읽는다

    id: int  # 사용자 번호
    name: str  # 이름
    email: str  # 이메일
    role: str  # 역할
    is_active: bool  # 활성 여부
    created_at: datetime  # 만든 시각
