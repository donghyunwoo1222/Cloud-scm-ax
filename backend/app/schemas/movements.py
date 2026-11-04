"""입출고 등록 요청·응답 모양 (POST /inventory-movements)."""

from datetime import date, datetime  # 날짜·시각 칸
from typing import Annotated, Literal  # 타입 검사, 정해진 값 중 하나

from pydantic import BaseModel, ConfigDict, Field, StringConstraints  # 모양 정의·검사 도구

# 이 경로로 넣을 수 있는 유형. CORRECTION 은 정정 경로(#30)로만 → 여기서 보내면 422
MovementType = Literal["RECEIPT", "SALE", "DISPOSAL", "OTHER_OUT", "ADJUSTMENT"]
Direction = Literal["IN", "OUT"]  # 늘림·줄임
SalesChannel = Literal["SMARTSTORE", "OWN_MALL", "OTHER"]  # 판매 채널
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]  # 사유: 공백만은 안 됨


class MovementCreate(BaseModel):
    # 모르는 칸은 422. 특히 purchase_order_item_id(발주 입고는 #35 경로)를 보내 초과 입고 검사를 우회하지 못하게
    model_config = ConfigDict(extra="forbid")

    product_id: Annotated[int, Field(strict=True)]  # 품목 (같은 회사 품목만, 비활성도 허용)
    movement_type: MovementType  # 입고·출고 3종·조정
    quantity: Annotated[int, Field(strict=True, ge=1)]  # 수량: 1 이상 정수 (늘고 줆은 유형·방향으로)
    direction: Direction | None = None  # 조정(ADJUSTMENT)일 때만 필수, 나머지는 서버가 정한다
    movement_date: date | None = None  # 입출고일, 비우면 서울 기준 오늘. 미래 날짜는 422
    sales_channel: SalesChannel | None = None  # 판매(SALE)일 때만 필수, 나머지는 비움
    reason: Reason | None = None  # 조정 사유 (ADJUSTMENT 필수)
    memo: Annotated[str, StringConstraints(max_length=1000)] | None = None  # 메모


class MovementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # InventoryMovement 객체에서 읽는다

    id: int  # 이력 번호
    product_id: int  # 품목
    movement_type: str  # 유형
    direction: str  # IN / OUT
    quantity: int  # 수량
    movement_date: date  # 입출고일
    sales_channel: str | None  # 판매 채널
    reason: str | None  # 사유
    memo: str | None  # 메모
    created_by: int  # 등록한 사용자
    created_at: datetime  # 등록 시각
