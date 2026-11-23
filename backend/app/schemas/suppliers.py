"""공급업체 요청·응답 모양."""

from datetime import datetime  # 시각 칸
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import (  # 모양 정의, ORM 객체에서 읽기 설정, 글자 길이
    BaseModel,
    ConfigDict,
    StringConstraints,
)

from app.schemas.common import (  # 공통 칸 타입·PATCH 규칙
    Currency,
    FreightTerms,
    LeadTimeDays,
    Memo,
    Name,
    OptionalText,
    PatchModel,
)

SpecialTerms = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None  # 특약 (발주서와 같은 한도)


class SupplierCreate(BaseModel):
    name: Name  # 업체명 (필수, 앞뒤 공백 제거. 대소문자는 구분)
    lead_time_days: LeadTimeDays  # 리드타임 일수 (필수, 0~365일)
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일 (로그인용이 아니라 형식 검사는 하지 않는다)
    memo: Memo = None  # 메모
    payment_terms: OptionalText = None  # 지불조건 기본값
    default_currency: Currency = "KRW"  # 기본 통화 (#267)
    default_freight_terms: FreightTerms | None = None  # 기본 운송비 조건
    default_special_terms: SpecialTerms = None  # 기본 특약


class SupplierUpdate(PatchModel):
    """바꿀 칸만 보낸다. 보내지 않은 칸은 그대로, 선택 칸에 null 을 보내면 비운다."""

    REQUIRED = ("name", "lead_time_days", "is_active", "default_currency")  # null 로 비울 수 없는 칸

    name: Name | None = None  # 업체명
    lead_time_days: LeadTimeDays | None = None  # 리드타임
    contact_name: OptionalText = None  # 담당자
    phone: OptionalText = None  # 연락처
    email: OptionalText = None  # 이메일
    memo: Memo = None  # 메모
    payment_terms: OptionalText = None  # 지불조건 기본값
    default_currency: Currency | None = None  # 기본 통화 (바꿔도 이미 만든 발주서는 그대로)
    default_freight_terms: FreightTerms | None = None  # 기본 운송비 조건 (null 이면 비움)
    default_special_terms: SpecialTerms = None  # 기본 특약 (null 이면 비움)
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
    payment_terms: str | None  # 지불조건 기본값
    default_currency: str  # 기본 통화
    default_freight_terms: str | None  # 기본 운송비 조건
    default_special_terms: str | None  # 기본 특약
    is_active: bool  # 활성 여부
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
