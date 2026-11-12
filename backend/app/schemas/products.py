"""품목 요청·응답 모양. 재고 숫자는 넣지 않는다(재고 조회는 #31)."""

from datetime import datetime  # 시각 칸
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import (  # 모양 정의·검사 도구
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    StringConstraints,
)

from app.schemas.common import (  # 공통 칸 타입(번호·단가·안전재고 상한 #71)·PATCH 규칙
    Id,
    Name,
    PatchModel,
    Quantity,
    SafetyStock,
    Won,
)

Sku = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),  # 앞뒤 공백 제거 후 1~50자
    AfterValidator(str.upper),  # 대문자로 바꿔 저장·비교 (ts-bk-m → TS-BK-M)
]
Unit = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]  # 단위: 개, 박스 등


def strip_or_none(value):
    """앞뒤 공백을 지우고, 비었으면 None. 예) "  검정 " → "검정", "   " → None (빈 글자가 값으로 저장되지 않게)."""
    return (value.strip() or None) if isinstance(value, str) else value


def limit_50(value):
    if value is not None and len(value) > 50:  # 비어 있지 않은 값만 길이를 본다 (Field(max_length)는 None 에서 오류가 난다)
        raise ValueError("50자 이하여야 합니다.")  # → 422 VALIDATION_ERROR
    return value


def limit_20(value):
    if value is not None and len(value) > 20:  # 발주단위 이름은 재고 단위처럼 20자까지
        raise ValueError("20자 이하여야 합니다.")
    return value


OrderUnit = Annotated[str | None, BeforeValidator(strip_or_none), AfterValidator(limit_20)]  # 발주단위 이름 (예: 박스, PACK)


def upper_or_none(value):
    return value.upper() if isinstance(value, str) else value  # 예) "ts-01" → "TS-01"


Option = Annotated[str | None, BeforeValidator(strip_or_none), AfterValidator(limit_50)]  # 옵션 칸: 선택, 최대 50자
GroupCode = Annotated[str | None, BeforeValidator(strip_or_none), AfterValidator(limit_50), AfterValidator(upper_or_none)]  # 그룹 코드: 대문자로 저장


class ProductCreate(BaseModel):
    sku: Sku  # 품목 코드 (회사 안에서 유일)
    name: Name  # 품목명
    unit: Unit  # 단위
    color: Option = None  # 옵션: 색상
    size: Option = None  # 옵션: 사이즈
    spec: Option = None  # 옵션: 규격
    group_code: GroupCode = None  # 그룹 코드
    unit_cost: Won  # 구매 단가 (원, 0~1억)
    units_per_box: Quantity | None = None  # 박스 하나에 들어 있는 재고 단위 수
    box_unit_cost: Won | None = None  # 박스당 구매 단가
    order_unit: OrderUnit = None  # 발주단위 이름. 박스 설정이 있는데 비우면 서버가 "박스"를 넣는다
    safety_stock: SafetyStock = 0  # 안전재고 (0~100만, 기본 0)
    default_supplier_id: Id  # 기본 공급업체 (필수, 같은 회사의 활성 업체만)


class ProductUpdate(PatchModel):
    """바꿀 칸만 보낸다. 박스 설정은 두 칸을 null로 보내 해제할 수 있다."""

    REQUIRED = ("sku", "name", "unit", "unit_cost", "safety_stock", "default_supplier_id", "is_active")

    sku: Sku | None = None  # 품목 코드
    name: Name | None = None  # 품목명
    unit: Unit | None = None  # 단위
    color: Option = None  # 색상 (null 이면 비움)
    size: Option = None  # 사이즈 (null 이면 비움)
    spec: Option = None  # 규격 (null 이면 비움)
    group_code: GroupCode = None  # 그룹 코드 (null 이면 비움)
    unit_cost: Won | None = None  # 단가
    units_per_box: Quantity | None = None  # 박스 입수
    box_unit_cost: Won | None = None  # 박스당 구매 단가
    order_unit: OrderUnit = None  # 발주단위 이름 (박스 설정을 해제하면 함께 비운다)
    safety_stock: SafetyStock | None = None  # 안전재고
    default_supplier_id: Id | None = None  # 기본 공급업체
    is_active: bool | None = None  # false: 비활성, true: 다시 활성


class SupplierBrief(BaseModel):
    """품목 응답에 같이 보여 줄 기본 공급업체 요약."""

    model_config = ConfigDict(from_attributes=True)  # Supplier 객체에서 읽는다

    id: int  # 공급업체 번호
    name: str  # 업체명
    lead_time_days: int  # 리드타임 (이 품목의 리드타임이 된다)


class ProductOut(BaseModel):
    id: int  # 품목 번호
    sku: str  # 품목 코드 (대문자)
    name: str  # 품목명
    unit: str  # 단위
    color: str | None  # 옵션: 색상 (없으면 null)
    size: str | None  # 옵션: 사이즈
    spec: str | None  # 옵션: 규격
    group_code: str | None  # 그룹 코드
    unit_cost: int  # 단가
    units_per_box: int | None  # 박스 입수
    box_unit_cost: int | None  # 박스당 구매 단가
    order_unit: str  # 발주단위 이름. 박스 설정이 없으면 재고 단위 (예: 개)
    unit_factor: int  # 환산계수: 발주단위 1개 = 재고 단위 몇 개. 박스 설정이 없으면 1
    safety_stock: int  # 안전재고
    is_active: bool  # 활성 여부
    default_supplier: SupplierBrief  # 기본 공급업체 id·이름·리드타임
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
