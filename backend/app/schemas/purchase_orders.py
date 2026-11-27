"""발주서 요청·응답 모양 (#33: 작성·수정·조회. 승인·발주·취소는 #34, 입고는 #35)."""

from datetime import date, datetime  # 날짜·시각 칸
from decimal import Decimal  # 외화 금액 응답 (JSON 에서는 글자, #267)
from typing import Annotated, Literal  # 타입에 검사를 덧붙이는 도구, 정해진 값 중 하나

from pydantic import (  # 모양 정의·검사 도구
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.common import (  # 공통 칸 타입(번호·수량·단가 상한 #71)·PATCH 규칙
    MAX_ORDER_LINES,
    BigWon,
    Currency,
    ExchangeRate,
    FreightTerms,
    FxPrice,
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
    unit_price: Won | None = None  # 원화 발주의 재고 단위 줄에서만 보내는 단가 (원)
    fx_price: FxPrice | None = None  # 외화 발주의 단가 (재고 단위 줄은 재고 단위당, 박스 줄은 발주단위당, #267)

    @model_validator(mode="after")
    def price_for_stock_quantity(self):
        if self.unit_price is not None and self.fx_price is not None:
            raise ValueError("unit_price와 fx_price를 함께 보낼 수 없습니다.")
        if self.quantity is not None and self.unit_price is None and self.fx_price is None:
            raise ValueError("재고 단위 발주에는 unit_price(원화) 또는 fx_price(외화)를 보내세요.")
        if self.quantity is None and self.unit_price is not None:
            raise ValueError("재고 단위 발주에만 unit_price를 보내세요.")
        return self


class ExtraCost(BaseModel):
    """부대비용 한 줄 (#267, 내부 전용). 금액은 원화 정수, 필수."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]  # 항목 이름 (예: 통관 수수료)
    amount: BigWon  # 금액 (원)


ExtraCosts = Annotated[list[ExtraCost], Field(max_length=20)]  # 부대비용 줄 최대 20개
SpecialTerms = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None  # 특약 (공급업체와 합의하는 글)


class CostFields(BaseModel):
    """작성·수정 공통 원가 칸 (#267). 작성에서 currency·freight_terms·special_terms 를 안 보내면 공급업체 기본값을 복사한다."""

    currency: Currency | None = None  # 통화 (작성에서 생략하면 공급업체 기본 통화)
    exchange_rate: ExchangeRate | None = None  # 기준 단위당 원 (외화만, 작성 중에는 비워도 되고 승인 때 필수)
    freight_terms: FreightTerms | None = None  # 운송비 조건 코드
    freight_amount: BigWon | None = None  # 운송비 (원). null = 미입력, 0 = 무료
    extra_costs: ExtraCosts | None = None  # 부대비용 줄 (null 은 빈 목록과 같다)
    special_terms: SpecialTerms = None  # 특약


class PurchaseOrderCreate(CostFields):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422 (status·po_number 를 못 정하게)

    supplier_id: Id  # 발주 대상 공급업체 (활성만)
    due_date: date | None = None  # 약속(희망) 납기
    memo: Memo = None  # 메모
    delivery_address: OptionalText = None  # 납품장소 (비우면 문서에 회사 주소)
    payment_terms: OptionalText = None  # 지불조건 (비우면 공급업체 기본값을 복사한다)
    items: Annotated[list[ItemIn], Field(min_length=1, max_length=MAX_ORDER_LINES)]  # 품목 줄 1~2000개 (초과는 422, #184)


class PurchaseOrderUpdate(CostFields, PatchModel):
    """DRAFT 일 때만. 보낸 칸만 바꾼다. items 를 보내면 그 목록이 최종 목록이다(없는 줄은 삭제).

    통화를 바꾸면 items 도 함께 보내야 한다(새 통화의 단가로 다시 입력, 서비스에서 422, #267).
    """

    model_config = ConfigDict(extra="forbid")  # 공급업체 변경 등은 422 (다른 업체 발주는 새 발주서로)

    REQUIRED = ("items", "currency")  # items·currency 에 null 은 422

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
    unit_price: int | None  # 발주 단가 (원). 외화 줄은 null (#267)
    fx_unit_price: Decimal | None = None  # 외화 줄의 재고 단위 단가 (발주서 통화)
    fx_box_unit_price: Decimal | None = None  # 외화 박스 줄의 발주단위 단가
    fx_line_total: Decimal | None = None  # 외화 줄 금액 (정확한 값, 원화 환산은 발주서 cost 에만)
    units_per_box: int | None  # 발주 당시 입수
    box_unit_price: int | None  # 발주 당시 박스당 단가
    box_quantity: int | None  # 박스 단위로 발주한 수량
    order_unit: str  # 발주 당시 발주단위 이름 (박스 줄이 아니면 재고 단위)
    unit_factor: int  # 발주 당시 환산계수 (박스 줄이 아니면 1)
    min_order_units: int | None = None  # 발주 당시 최소 주문량(발주단위 수) 스냅샷 (#194)
    line_total: int | None  # 박스 발주 금액은 박스 수 × 박스 단가 (원). 외화 줄은 null (줄에 원화를 보이지 않는다, #282)
    recommended_quantity: int | None  # 추천으로 만든 줄이면 당시 추천 수량
    recommendation_reason: str | None  # 당시 추천 이유 문장
    received_quantity: int  # 누적 입고량 = 입고 − 입고 정정 (이력 합계)
    closed_quantity: int | None = None  # 잔량 마감 수량 = 발주 − 누적 입고 (RECEIVED 일 때만, 그 외 null. 저장하지 않고 계산, #252)


class CostOut(BaseModel):
    """원가 합산 (#267, 서버 계산, 저장하지 않는다). 원가 = 품목 원화 합계 + 운송비 + 부대비용 (부가세 미포함)."""

    goods_fx_total: Decimal | None  # 외화 발주의 품목 외화 합계 (원화 발주는 null)
    goods_krw: int | None  # 품목 원화 합계 (승인 뒤는 스냅샷, 외화인데 환율이 없으면 null)
    freight: int | None  # 운송비 (null = 미입력)
    extras_total: int  # 부대비용 합계
    total: int | None  # 원가 (goods_krw 가 없으면 null)
    missing: list[str]  # 미입력 항목: exchange_rate, freight
    received_goods_krw: int | None  # 입고 기준 품목 원화 합계 (발주함·입고 완료만, 마감 수량 제외)
    received_total: int | None  # 입고 기준 원가 (운송비·부대비용은 전액)


class PurchaseOrderOut(BaseModel):
    id: int  # 발주서 번호
    po_number: str  # 발주번호 (예: PO-20261104-001)
    supplier_id: int  # 공급업체
    supplier_name: str  # 공급업체명
    status: str  # DRAFT / APPROVED / ORDERED / RECEIVED / CANCELLED
    due_date: date | None  # 약속 납기
    supplier_due_date: date | None  # 공급업체 회신 납기 (#265, 없으면 null)
    supplier_confirmed_at: datetime | None  # 공급업체 확인 시각 (#265)
    supplier_reply_count: int  # 공급업체 회신 횟수 (#265)
    memo: str | None  # 메모
    delivery_address: str | None  # 납품장소
    payment_terms: str | None  # 지불조건
    created_by: int  # 작성자
    approved_by: int | None  # 승인자
    approved_at: datetime | None  # 승인 시각
    ordered_at: datetime | None  # 발주함 표시 시각
    received_at: datetime | None  # 전량 입고 시각 (실제 입고일)
    has_receipts: bool  # 전량 정정된 입고 기록도 포함한다.
    allowed_actions: list[str] = []  # 지금 누를 수 있는 동작 (#260 PR3, po_states.allowed_actions). 화면 버튼은 이것만 따른다
    cancelled_at: datetime | None  # 취소 시각
    emailed_at: datetime | None  # 마지막 메일 발송 시각 (#158, 보낸 적 없으면 비움)
    emailed_to: str | None  # 마지막 메일 수신 주소 (#158)
    emailed_by: int | None  # 마지막 메일 보낸 사용자 (#158)
    created_at: datetime  # 만든 시각
    updated_at: datetime  # 고친 시각
    currency: str  # 통화 (#267)
    rate_unit: int  # 환율 기준 단위 (엔·동 100)
    exchange_rate: Decimal | None  # 기준 단위당 원 (원화는 null)
    krw_goods_total: int | None  # 승인 때 고정한 품목 원화 합계 (승인 전 null)
    freight_terms: str | None  # 운송비 조건 코드
    freight_amount: int | None  # 운송비 (원, 내부 전용)
    extra_costs: list[ExtraCost]  # 부대비용 줄 (원, 내부 전용)
    special_terms: str | None  # 특약
    source_po_id: int | None = None  # 복사해 만든 발주서면 원본 발주서 번호 (#188)
    cost: CostOut  # 원가 합산 (서버 계산, 내부 전용)
    items: list[ItemOut]  # 품목 줄


class OrderCancel(BaseModel):
    """POST /purchase-orders/{id}/cancel 선택 본문 (#181). 본문이 없어도 된다. 발주함(ORDERED) 취소는 reason 필수(서비스에서 검사)."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    reason: Annotated[str, Field(max_length=500)] | None = None  # 취소 사유 (최대 500자)


class OrderCloseRemaining(BaseModel):
    """POST /purchase-orders/{id}/close-remaining 본문 (#252). 사유 필수 (공백뿐이면 서비스에서 422)."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    reason: Annotated[str, Field(max_length=500)]  # 잔량 마감 사유 (최대 500자, 취소 사유와 같은 한도)


class SupplierReplyRecord(BaseModel):
    """POST /purchase-orders/{id}/supplier-reply 본문 (#265 PR4). 직원이 받은 공급업체 회신. 행위자·회사는 로그인에서만 가져온다."""

    model_config = ConfigDict(extra="forbid")  # changed_by·company_id 같은 칸은 422

    due_date: date | None = None  # 회신 납기 (비우면 확인만, 범위는 서비스: 서울 기준 오늘 ~ 1년 뒤)
    reason: Annotated[str, Field(max_length=500)]  # 받은 경로·메모 (필수, 공백뿐이면 서비스에서 422)


class ChangeLogOut(BaseModel):
    id: int  # 이력 번호
    field: str  # 바뀐 항목 (예: status, due_date, items[SKU].quantity)
    old_value: str | None  # 변경 전 값
    new_value: str | None  # 변경 후 값
    changed_by_name: str  # 바꾼 사용자 이름 (이메일·번호는 내보내지 않는다)
    reason: str | None  # 사유 (취소 때)
    created_at: datetime  # 바뀐 시각


class EmailLogOut(BaseModel):
    """메일 발송 시도 이력 한 행(#182). 토큰·본문·실패 원문은 표에도 응답에도 없다."""

    id: int  # 이력 번호
    kind: Literal["ORDER", "REMINDER"]  # 발주서 메일 / 납기 독촉(#269)
    to_address: str | None  # 그때의 받는 주소 (옛 기록에서 비어 있을 수 있다)
    sent_by_name: str  # 보낸 사람 이름 (이메일·번호는 내보내지 않는다, 모르면 빈 글자)
    result: Literal["SENT", "FAILED", "UNSAVED"]  # 성공 / 실패 / 메일은 나갔으나 저장 실패
    failure_code: str | None  # 실패 종류 코드 (FAILED 일 때만)
    with_link: bool | None  # 확인 링크를 넣었는지 (옛 기록은 모름)
    created_at: datetime  # 시각


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


class ReminderSend(BaseModel):
    """POST /purchase-orders/{id}/reminder 본문 (#269). 받는 사람·제목·고정 부분은 서버가 만들고, 사용자는 앞머리만 보낸다."""

    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422 (받는 주소·품목을 본문으로 바꿔치기할 수 없다)

    intro: Annotated[str, Field(min_length=1, max_length=2000)]  # 앞머리 한 문단 (빈 글자는 422, 발주서 메일과 같은 길이)


class PriceCheckItem(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    product_id: Id  # 확인할 품목
    unit_price: Won | None = None  # 입력 중인 재고 단위 단가(원). 비었으면 비교하지 않는다 (빈 값을 0으로 보지 않는다)


class PriceCheck(BaseModel):
    """POST /purchase-orders/price-check 요청 (#283). 회사는 본문이 아니라 로그인 토큰에서만 정한다."""

    model_config = ConfigDict(extra="forbid")

    supplier_id: Id  # 이 공급업체의 직전 발주와 비교한다
    items: Annotated[list[PriceCheckItem], Field(min_length=1, max_length=MAX_ORDER_LINES)]  # 발주서 줄 수 상한과 같다
