"""재고 조회 응답 모양 (GET /stock). 부족 상태·발주 진행 중 수량은 추천(#39) 계산과 함께 만든다."""

from pydantic import BaseModel  # 모양 정의


class StockOut(BaseModel):
    product_id: int  # 품목
    sku: str  # SKU
    name: str  # 품목명
    unit: str  # 단위
    safety_stock: int  # 안전재고
    is_active: bool  # 활성 여부
    current_stock: int  # 현재고 = 입출고 이력 합계
