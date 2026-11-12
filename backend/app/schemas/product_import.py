"""품목 마스터 가져오기 요청 모양 (#189). 파일은 multipart 로, 아래 설정은 JSON 글자 한 칸(options)으로 받는다."""

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구

from app.schemas.common import (  # 칸 타입은 품목 등록(ProductCreate)과 같은 것을 그대로 쓴다
    Id,
    Name,
    Quantity,
    SafetyStock,
    Won,
)
from app.schemas.products import GroupCode, Option, OrderUnit, Unit
from app.schemas.receipt_import import Col  # 선택 열 번호 (0부터, 없으면 None)

REQUIRED_COL = Field(ge=0, le=1000)  # 필수 열 번호


class ProductImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    product_col: int = REQUIRED_COL  # SKU 열 (필수)
    name_col: int = REQUIRED_COL  # 품목명 열 (필수. 기존 품목 행은 칸이 비어도 된다 = 변경 없음)
    unit_col: int = REQUIRED_COL  # 기본단위 열 (필수)
    cost_col: int = REQUIRED_COL  # 구매단가 열 (필수. 신규 품목 행은 칸도 필수)
    safety_col: int | None = Col  # 안전재고
    order_unit_col: int | None = Col  # 발주단위 이름
    factor_col: int | None = Col  # 환산계수 (= units_per_box)
    box_cost_col: int | None = Col  # 발주단위 단가 (= box_unit_cost)
    moq_col: int | None = Col  # 최소 주문량 (발주단위 수)
    color_col: int | None = Col
    size_col: int | None = Col
    spec_col: int | None = Col
    group_col: int | None = Col
    default_supplier_id: Id | None = None  # 새 품목의 기본 공급업체 (새 품목이 있을 때 반영에 필수). 기존 품목에는 쓰지 않는다
    exclude_problems: bool = False  # 문제 행을 빼고 반영할지
    expected_new_count: int | None = Field(default=None, ge=0, le=100_000)  # (선택) 미리보기에서 본 신규 건수. 반영 결과와 비교해 달라지면 알려 준다
    expected_update_count: int | None = Field(default=None, ge=0, le=100_000)  # (선택) 미리보기에서 본 수정 건수


class ProductRow(BaseModel):
    """파일 한 행에서 읽은 값. 비어 있지 않은 칸만 넣어 검사한다(빈 칸 = 변경 없음). 칸 규칙은 품목 등록과 같다."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    unit: Unit | None = None
    unit_cost: Won | None = None
    safety_stock: SafetyStock | None = None
    order_unit: OrderUnit = None
    units_per_box: Quantity | None = None  # 환산계수 (1 이상 정수: 0·음수·소수는 422)
    box_unit_cost: Won | None = None
    min_order_units: Quantity | None = None
    color: Option = None
    size: Option = None
    spec: Option = None
    group_code: GroupCode = None
