"""재고 조회 응답 모양 (GET /stock). 부족 상태·발주 진행 중 수량은 추천 계산과 같은 함수로 붙인다(#76)."""

from typing import Literal  # 정해진 값만

from pydantic import BaseModel  # 모양 정의

Status = Literal["SHORTAGE", "NORMAL", "UNKNOWN"]  # 부족 / 정상 / 판단 불가


class StockOut(BaseModel):
    product_id: int  # 품목
    sku: str  # SKU
    name: str  # 품목명
    unit: str  # 단위
    safety_stock: int  # 안전재고
    is_active: bool  # 활성 여부
    current_stock: int  # 현재고 = 입출고 이력 합계
    in_transit: int  # 발주 진행 중(ORDERED 미입고) 수량
    status: Status | None  # 재고 상태. 비활성 품목은 계산하지 않아 null
    status_reason: dict | None  # 판단 불가 이유 {code, message} (예: INSUFFICIENT_DATA, "데이터 부족"). 그 밖은 null
