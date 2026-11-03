"""공급업체 요청·응답 모양."""

from datetime import datetime  # 시각 칸
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import (  # 모양 정의·검사 도구
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]  # 업체명: 앞뒤 공백 제거 후 1~100자
LeadTime = Annotated[int, Field(ge=0, strict=True)]  # 리드타임: 0 이상 정수만 (strict: 3.5·3.0·"3" 같은 값은 422)
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None  # 선택 칸: 200자까지, 비워도 됨
Memo = Annotated[str, StringConstraints(max_length=1000)] | None  # 메모: 1000자까지


class SupplierCreate(BaseModel):
    name: Name  # 업체명 (필수)
    lead_time_days: LeadTime  # 리드타임 일수 (필수)
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일 (로그인용이 아니라 형식 검사는 하지 않는다)
    memo: Memo = None  # 메모


class SupplierUpdate(BaseModel):
    """바꿀 칸만 보낸다. 보내지 않은 칸은 그대로, 선택 칸에 null 을 보내면 비운다."""

    name: Name | None = None  # 업체명
    lead_time_days: LeadTime | None = None  # 리드타임
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일
    memo: Memo = None  # 메모
    is_active: bool | None = None  # false: 비활성, true: 다시 활성

    @model_validator(mode="after")
    def required_fields_not_null(self):
        """필수 칸(업체명·리드타임·활성 여부)은 null 로 비울 수 없다."""
        for field in ("name", "lead_time_days", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:  # 보냈는데 null 이면
                raise ValueError(f"{field} 는 비울 수 없습니다.")  # → 422 VALIDATION_ERROR
        return self


class SupplierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Supplier 객체에서 같은 이름의 칸을 읽는다

    id: int  # 공급업체 번호
    name: str  # 업체명
    lead_time_days: int  # 리드타임
    contact_name: str | None  # 담당자
    phone: str | None  # 연락처
    email: str | None  # 이메일
    memo: str | None  # 메모
    is_active: bool  # 활성 여부
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
