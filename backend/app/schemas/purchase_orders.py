"""발주서 요청·응답 모양 (#33: 작성·수정·조회. 승인·발주·취소는 #34, 입고는 #35)."""

from datetime import date, datetime  # 날짜·시각 칸
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구

from app.schemas.common import Memo, NonNegInt, PatchModel  # 공통 칸 타입·PATCH 규칙

PosInt = Annotated[int, Field(ge=1, strict=True)]  # 1 이상 정수만 (3.0·"3"·true 는 422)
Id = Annotated[int, Field(strict=True)]  # 번호 칸 (정수만)


class ItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸(추천 근거 등 서버가 정하는 값)은 422

    product_id: Id  # 발주할 품목 (같은 회사, 활성 품목만 새로 넣을 수 있다)
    quantity: PosInt  # 발주 수량 (1 이상)
    unit_price: NonNegInt  # 발주 당시 단가 (원, 0 이상)


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422 (status·po_number 를 못 정하게)

    supplier_id: Id  # 발주 대상 공급업체 (활성만)
    due_date: date | None = None  # 약속(희망) 납기
    memo: Memo = None  # 메모
    items: Annotated[list[ItemIn], Field(min_length=1)]  # 품목 줄 1개 이상


class PurchaseOrderUpdate(PatchModel):
    """DRAFT 일 때만. 보낸 칸만 바꾼다. items 를 보내면 그 목록이 최종 목록이다(없는 줄은 삭제)."""

    model_config = ConfigDict(extra="forbid")  # 공급업체 변경 등은 422 (다른 업체 발주는 새 발주서로)

    REQUIRED = ("items",)  # items 에 null 은 422 (비우려면 보내지 않는다)

    due_date: date | None = None  # 약속 납기 (null 이면 비움)
    memo: Memo = None  # 메모 (null 이면 비움)
    items: Annotated[list[ItemIn], Field(min_length=1)] | None = None  # 최종 품목 줄 목록


class ItemOut(BaseModel):
    id: int  # 발주 품목 번호
    product_id: int  # 품목
    product_sku: str  # 품목 SKU
    product_name: str  # 품목명
    quantity: int  # 발주 수량
    unit_price: int  # 발주 단가
    recommended_quantity: int | None  # 추천으로 만든 줄이면 당시 추천 수량
    recommendation_reason: str | None  # 당시 추천 이유 문장
    received_quantity: int  # 누적 입고량 = 입고 − 입고 정정 (이력 합계)


class PurchaseOrderOut(BaseModel):
    id: int  # 발주서 번호
    po_number: str  # 발주번호 (예: PO-20261104-001)
    supplier_id: int  # 공급업체
    supplier_name: str  # 공급업체명
    status: str  # DRAFT / APPROVED / ORDERED / RECEIVED / CANCELLED
    due_date: date | None  # 약속 납기
    memo: str | None  # 메모
    created_by: int  # 작성자
    approved_by: int | None  # 승인자
    approved_at: datetime | None  # 승인 시각
    ordered_at: datetime | None  # 발주함 표시 시각
    received_at: datetime | None  # 전량 입고 시각 (실제 입고일)
    cancelled_at: datetime | None  # 취소 시각
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
    items: list[ItemOut]  # 품목 줄
