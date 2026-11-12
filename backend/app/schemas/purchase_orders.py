"""발주서 요청·응답 모양 (#33: 작성·수정·조회. 승인·발주·취소는 #34, 입고는 #35)."""

from datetime import date, datetime  # 날짜·시각 칸
from typing import Annotated, Literal  # 타입에 검사를 덧붙이는 도구, 정해진 값 중 하나

from pydantic import BaseModel, ConfigDict, Field, model_validator  # 모양 정의·검사 도구

from app.schemas.common import (  # 공통 칸 타입(번호·수량·단가 상한 #71)·PATCH 규칙
    MAX_ORDER_LINES,
    Id,
    Memo,
    OptionalText,
    PatchModel,
    Quantity,
    Won,
)

PoStatus = Literal["DRAFT", "APPROVED", "ORDERED", "RECEIVED", "CANCELLED"]  # 목록 상태 필터 (그 밖의 값은 422)
ReceiptDue = Literal["OVERDUE", "TODAY", "NEXT_7_DAYS", "UNSCHEDULED"]  # 발주함 발주의 납기 구간


class OrderQuantity(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    quantity: Quantity | None = None  # 재고 기준 수량
    box_quantity: Quantity | None = None  # 박스 수

    @model_validator(mode="after")
    def one_quantity(self):
        if (self.quantity is None) == (self.box_quantity is None):
            raise ValueError("quantity 또는 box_quantity 중 하나를 보내세요.")
        return self


class ItemIn(OrderQuantity):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸(추천 근거 등 서버가 정하는 값)은 422

    product_id: Id  # 발주할 품목 (같은 회사, 활성 품목만 새로 넣을 수 있다)
    unit_price: Won | None = None  # 재고 단위 발주에서만 요청에 포함하는 단가

    @model_validator(mode="after")
    def price_for_stock_quantity(self):
        if (self.quantity is None) != (self.unit_price is None):
            raise ValueError("재고 단위 발주에만 unit_price를 보내세요.")
        return self


class PurchaseOrderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422 (status·po_number 를 못 정하게)

    supplier_id: Id  # 발주 대상 공급업체 (활성만)
    due_date: date | None = None  # 약속(희망) 납기
    memo: Memo = None  # 메모
    delivery_address: OptionalText = None  # 납품장소 (비우면 문서에 회사 주소)
    payment_terms: OptionalText = None  # 지불조건 (비우면 공급업체 기본값을 복사한다)
    items: Annotated[list[ItemIn], Field(min_length=1, max_length=MAX_ORDER_LINES)]  # 품목 줄 1~2000개 (초과는 422, #184)


class PurchaseOrderUpdate(PatchModel):
    """DRAFT 일 때만. 보낸 칸만 바꾼다. items 를 보내면 그 목록이 최종 목록이다(없는 줄은 삭제)."""

    model_config = ConfigDict(extra="forbid")  # 공급업체 변경 등은 422 (다른 업체 발주는 새 발주서로)

    REQUIRED = ("items",)  # items 에 null 은 422 (비우려면 보내지 않는다)

    due_date: date | None = None  # 약속 납기 (null 이면 비움)
    memo: Memo = None  # 메모 (null 이면 비움)
    delivery_address: OptionalText = None  # 납품장소 (null 이면 비움)
    payment_terms: OptionalText = None  # 지불조건 (null 이면 비움)
    items: Annotated[list[ItemIn], Field(min_length=1, max_length=MAX_ORDER_LINES)] | None = None  # 최종 품목 줄 목록


class ItemOut(BaseModel):
    id: int  # 발주 품목 번호
    product_id: int  # 품목
    product_sku: str  # 품목 SKU
    product_name: str  # 품목명
    color: str | None = None  # 품목 옵션: 색상 (품목 마스터의 현재 값)
    size: str | None = None  # 품목 옵션: 사이즈
    spec: str | None = None  # 품목 옵션: 규격
    group_code: str | None = None  # 품목 그룹 코드
    unit: str  # 품목 단위 (품목 마스터의 현재 값, 개·박스 등)
    quantity: int  # 발주 수량
    unit_price: int  # 발주 단가
    units_per_box: int | None  # 발주 당시 입수
    box_unit_price: int | None  # 발주 당시 박스당 단가
    box_quantity: int | None  # 박스 단위로 발주한 수량
    order_unit: str  # 발주 당시 발주단위 이름 (박스 줄이 아니면 재고 단위)
    unit_factor: int  # 발주 당시 환산계수 (박스 줄이 아니면 1)
    min_order_units: int | None = None  # 발주 당시 최소 주문량(발주단위 수) 스냅샷 (#194)
    line_total: int  # 박스 발주 금액은 박스 수 × 박스 단가
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
    delivery_address: str | None  # 납품장소
    payment_terms: str | None  # 지불조건
    created_by: int  # 작성자
    approved_by: int | None  # 승인자
    approved_at: datetime | None  # 승인 시각
    ordered_at: datetime | None  # 발주함 표시 시각
    received_at: datetime | None  # 전량 입고 시각 (실제 입고일)
    has_receipts: bool  # 전량 정정된 입고 기록도 포함한다.
    cancelled_at: datetime | None  # 취소 시각
    emailed_at: datetime | None  # 마지막 메일 발송 시각 (#158, 보낸 적 없으면 비움)
    emailed_to: str | None  # 마지막 메일 수신 주소 (#158)
    emailed_by: int | None  # 마지막 메일 보낸 사용자 (#158)
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
    items: list[ItemOut]  # 품목 줄


class ReceiptLine(OrderQuantity):
    purchase_order_item_id: Id  # 입고할 발주 줄 (이 발주서의 줄만)


class ReceiptCreate(BaseModel):
    """POST /purchase-orders/{id}/receipts 본문 (#35). 여러 줄을 한 번에, 모두 저장되거나 모두 취소된다."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    movement_date: date | None = None  # 입고일. 비우면 서울 오늘, 미래 날짜는 422
    items: Annotated[list[ReceiptLine], Field(min_length=1)]  # 입고 줄 1개 이상
    confirm_warnings: bool = False  # 409 CONFIRM_REQUIRED 경고(큰 수량)를 사용자가 확인했으면 true 로 다시 보낸다 (#190)


class OrderEmailSend(BaseModel):
    """POST /purchase-orders/{id}/email 본문 (#158). 받는 사람·제목·고정 부분은 서버가 만들고, 사용자는 앞머리만 보낸다."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422 (받는 주소를 본문으로 바꿔치기할 수 없다)

    intro: Annotated[str, Field(min_length=1, max_length=2000)]  # 앞머리 한 문단 (빈 글자는 422)
    resend: bool = False  # 이미 발주함(ORDERED)인 발주서를 다시 보낼 때만 true (확인창에서 한 번 더 물은 뒤)
