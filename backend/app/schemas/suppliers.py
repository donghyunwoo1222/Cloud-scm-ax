"""공급업체 요청·응답 모양."""

from datetime import datetime  # 시각 칸

from pydantic import BaseModel, ConfigDict  # 모양 정의, ORM 객체에서 읽기 설정

from app.schemas.common import (  # 공통 칸 타입·PATCH 규칙
    LeadTimeDays,
    Memo,
    Name,
    OptionalText,
    PatchModel,
)


class SupplierCreate(BaseModel):
    name: Name  # 업체명 (필수, 앞뒤 공백 제거. 대소문자는 구분)
    lead_time_days: LeadTimeDays  # 리드타임 일수 (필수, 0~365일)
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일 (로그인용이 아니라 형식 검사는 하지 않는다)
    memo: Memo = None  # 메모


class SupplierUpdate(PatchModel):
    """바꿀 칸만 보낸다. 보내지 않은 칸은 그대로, 선택 칸에 null 을 보내면 비운다."""

    REQUIRED = ("name", "lead_time_days", "is_active")  # null 로 비울 수 없는 칸

    name: Name | None = None  # 업체명
    lead_time_days: LeadTimeDays | None = None  # 리드타임
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일
    memo: Memo = None  # 메모
    is_active: bool | None = None  # false: 비활성, true: 다시 활성


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
