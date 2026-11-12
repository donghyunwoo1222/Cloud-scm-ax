"""재고 조회 응답 모양 (GET /stock). 부족 상태·발주 진행 중 수량은 추천 계산과 같은 함수로 붙인다(#76)."""

from datetime import date  # 서울 기준 업무 날짜
from typing import Literal  # 정해진 값만

from pydantic import BaseModel  # 모양 정의

Status = Literal["SHORTAGE", "NORMAL", "UNKNOWN"]  # 부족 / 정상 / 판단 불가


class StockOut(BaseModel):
    product_id: int  # 품목
    sku: str  # SKU
    name: str  # 품목명
    unit: str  # 단위
    color: str | None = None  # 옵션: 색상 (없으면 null)
    size: str | None = None  # 옵션: 사이즈
    spec: str | None = None  # 옵션: 규격
    group_code: str | None = None  # 그룹 코드
    safety_stock: int  # 안전재고
    is_active: bool  # 활성 여부
    current_stock: int  # 현재고 = 입출고 이력 합계
    in_transit: int  # 발주 진행 중(ORDERED 미입고) 수량
    reorder_point: float | None  # 판정에 사용한 재주문점 (판단 불가·비활성은 null)
    status: Status | None  # 재고 상태. 비활성 품목은 계산하지 않아 null
    status_reason: dict | None  # 판단 불가 이유 {code, message} (예: INSUFFICIENT_DATA, "데이터 부족"). 그 밖은 null


class StockTrendDay(BaseModel):
    day: date  # 서울 기준 입출고일
    closing_stock: int | None  # 첫 이력 전은 null, 첫 이력 뒤에는 변동 없는 날도 수량을 이어 간다
    received_quantity: int  # 그날 입고량에서 입고 정정을 뺀 값
    reached_zero: bool  # 직전 마감에는 재고가 있었고 이날 0이 됐다


class StockTrendOut(BaseModel):
    product_id: int
    name: str
    sku: str
    unit: str
    days: list[StockTrendDay]  # 오래된 날짜부터 오늘까지 30일
