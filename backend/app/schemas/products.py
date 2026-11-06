"""품목 요청·응답 모양. 재고 숫자는 넣지 않는다(재고 조회는 #31)."""

from datetime import datetime  # 시각 칸
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import (  # 모양 정의·검사 도구
    AfterValidator,
    BaseModel,
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


class ProductCreate(BaseModel):
    sku: Sku  # 품목 코드 (회사 안에서 유일)
    name: Name  # 품목명
    unit: Unit  # 단위
    unit_cost: Won  # 구매 단가 (원, 0~1억)
    units_per_box: Quantity | None = None  # 박스 하나에 들어 있는 재고 단위 수
    box_unit_cost: Won | None = None  # 박스당 구매 단가
    safety_stock: SafetyStock = 0  # 안전재고 (0~100만, 기본 0)
    default_supplier_id: Id  # 기본 공급업체 (필수, 같은 회사의 활성 업체만)


class ProductUpdate(PatchModel):
    """바꿀 칸만 보낸다. 박스 설정은 두 칸을 null로 보내 해제할 수 있다."""

    REQUIRED = ("sku", "name", "unit", "unit_cost", "safety_stock", "default_supplier_id", "is_active")

    sku: Sku | None = None  # 품목 코드
    name: Name | None = None  # 품목명
    unit: Unit | None = None  # 단위
    unit_cost: Won | None = None  # 단가
    units_per_box: Quantity | None = None  # 박스 입수
    box_unit_cost: Won | None = None  # 박스당 구매 단가
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
    unit_cost: int  # 단가
    units_per_box: int | None  # 박스 입수
    box_unit_cost: int | None  # 박스당 구매 단가
    safety_stock: int  # 안전재고
    is_active: bool  # 활성 여부
    default_supplier: SupplierBrief  # 기본 공급업체 id·이름·리드타임
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
