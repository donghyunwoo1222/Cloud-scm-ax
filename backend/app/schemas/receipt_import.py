"""품목·입고 가져오기 요청 모양 (#155). 파일은 multipart 로, 아래 설정은 JSON 글자 한 칸(options)으로 받는다."""

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구

from app.schemas.common import (  # 번호·이름·안전재고·단가 규칙 (품목 등록과 같다)
    Id,
    Name,
    SafetyStock,
    Won,
)
from app.schemas.products import Sku, Unit  # SKU(대문자)·단위 규칙

Col = Field(default=None, ge=0, le=1000)  # 선택 열 번호 (0부터, 없으면 None)


class ReceiptImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    product_col: int = Field(ge=0, le=1000)  # 상품 코드(SKU) 열 (필수)
    quantity_col: int | None = Col  # 수량 열. 없으면 "품목만 등록" 모드
    date_col: int | None = Col  # 입고일 열 (수량 열이 있으면 필수)
    ref_col: int | None = Col  # (선택) 고유 번호 열. 없으면 내용(날짜|SKU|수량|n번째)으로 번호를 만든다
    name_col: int | None = Col  # 새 품목: 품목명 열
    unit_col: int | None = Col  # 새 품목: 단위 열
    cost_col: int | None = Col  # 새 품목: 단가 열
    safety_col: int | None = Col  # 새 품목: (선택) 안전재고 열, 비면 0
    supplier_col: int | None = Col  # (선택) 공급업체 열: 새 품목의 업체가 섞였는지 확인만 한다 (2곳 이상이면 422)
    default_supplier_id: Id | None = None  # 새 품목의 기본 공급업체 (새 품목이 있을 때 반영에 필수)
    exclude_problems: bool = False  # 문제 행을 빼고 반영할지


class NewProduct(BaseModel):
    """파일 한 행에서 읽은 새 품목 값. 품목 등록(ProductCreate)과 같은 칸 규칙으로 검사한다."""

    sku: Sku
    name: Name
    unit: Unit
    unit_cost: Won
    safety_stock: SafetyStock = 0
