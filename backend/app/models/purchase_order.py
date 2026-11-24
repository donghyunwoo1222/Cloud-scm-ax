from datetime import date, datetime  # 날짜·시각 칸의 파이썬 타입
from decimal import Decimal  # 외화 단가·환율 (float 금지, #267)

from sqlalchemy import (  # 제약·인덱스 도구
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB  # 부대비용 줄 목록 (#267)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class PurchaseOrder(CompanyMixin, Base):
    """발주서: 공급업체 한 곳에 보내는 발주 한 장."""

    __tablename__ = "purchase_orders"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("company_id", "po_number", name="uq_purchase_orders_company_po_number"),  # 회사 안에서 발주번호 중복 불가
        CheckConstraint(
            "status IN ('DRAFT', 'APPROVED', 'ORDERED', 'RECEIVED', 'CANCELLED')",  # 상태는 다섯 값 중 하나만
            name="ck_purchase_orders_status",
        ),
        Index(
            "one_draft_per_supplier",  # 부분 고유 인덱스 (S10)
            "company_id",
            "supplier_id",  # 회사 + 공급업체 조합마다
            unique=True,
            postgresql_where=text("status = 'DRAFT'"),  # DRAFT인 행끼리만 유일 검사 → 공급업체당 DRAFT 1장
        ),
        # 원가 칸 (#267). 통화 목록은 po_money.CURRENCIES 와 같다
        CheckConstraint("currency IN ('KRW', 'USD', 'EUR', 'JPY', 'CNY', 'VND')", name="ck_purchase_orders_currency"),
        CheckConstraint("rate_unit IN (1, 100) AND (currency IN ('JPY', 'VND')) = (rate_unit = 100)",
                        name="ck_purchase_orders_rate_unit"),  # 기준 단위: 엔·동 100, 그 밖 1 (po_money.CURRENCIES 와 같다)
        CheckConstraint("NOT (currency = 'KRW' AND exchange_rate IS NOT NULL) AND exchange_rate > 0",
                        name="ck_purchase_orders_exchange_rate"),  # 원화는 환율 없음, 외화는 작성 중 비어도 되지만 있으면 0 초과
        CheckConstraint("approved_at IS NULL OR currency = 'KRW' OR exchange_rate IS NOT NULL",
                        name="ck_purchase_orders_fx_rate_approved"),  # 승인한 외화 발주서는 환율이 있다
        CheckConstraint("approved_at IS NULL OR krw_goods_total IS NOT NULL",
                        name="ck_purchase_orders_krw_goods_total"),  # 승인한 발주서(승인 뒤 취소 포함)는 원화 스냅샷이 있다
        CheckConstraint("krw_goods_total >= 0 AND freight_amount >= 0", name="ck_purchase_orders_cost_amounts"),
        CheckConstraint("freight_terms IN ('INCLUDED', 'BILLED', 'COLLECT', 'EXW', 'FOB', 'CIF', 'DDP')",
                        name="ck_purchase_orders_freight_terms"),
    )

    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))  # 발주 대상 공급업체
    po_number: Mapped[str]  # 발주번호 (시스템이 부여)
    status: Mapped[str] = mapped_column(server_default="DRAFT")  # 상태, 기본 DRAFT
    due_date: Mapped[date | None]  # 약속(희망) 납기
    memo: Mapped[str | None]  # 메모
    delivery_address: Mapped[str | None]  # 납품장소 (비우면 문서에는 회사 주소가 나온다, #157)
    payment_terms: Mapped[str | None]  # 지불조건 (만들 때 공급업체 기본값을 복사, 발주서에서 수정 가능, #157)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 작성자
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 승인자 (승인 전에는 비움)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 승인 시각
    approved_company_name: Mapped[str | None]  # 승인 시점 회사명 (문서 도장용 스냅샷, 회사명이 나중에 바뀌어도 그대로, #263)
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # ORDERED로 바뀐 시각
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # RECEIVED로 바뀐 시각
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # CANCELLED로 바뀐 시각
    # 메일 발송 기록 (#158): 이력 표 없이 마지막 1건만 남긴다 (다시 보내면 덮어쓴다)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 마지막 발송 시각 (메일 서버가 받은 시각, 공급업체 수신 확인 아님)
    emailed_to: Mapped[str | None]  # 마지막 수신 주소 (그때의 공급업체 이메일, 나중에 업체 이메일을 바꿔도 남는다)
    emailed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 마지막으로 보낸 사용자
    # 공급업체 회신 (#265): 새 상태 없이 칸과 변경 이력으로만 표현한다. 약속 납기(due_date)는 덮어쓰지 않는다.
    supplier_token_hash: Mapped[str | None] = mapped_column(unique=True)  # 메일 링크 토큰의 해시 (내부 전용, 응답에 내보내지 않는다)
    supplier_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 토큰 만료 시각 (내부 전용)
    supplier_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 공급업체가 확인한 시각
    supplier_due_date: Mapped[date | None]  # 공급업체가 회신한 납기 (계산은 회신이 있으면 이 날짜를 쓴다)
    supplier_reply_count: Mapped[int] = mapped_column(Integer, server_default="0", default=0)  # 회신 횟수
    # 원가 (#267): 작성 중(DRAFT)에만 고칠 수 있고 승인하면 그대로 고정된다. NULL = 미입력, 0 = 0원
    currency: Mapped[str] = mapped_column(server_default="KRW")  # 통화 (만들 때 공급업체 기본 통화를 복사)
    rate_unit: Mapped[int] = mapped_column(Integer, server_default="1")  # 환율 기준 단위 스냅샷 (엔·동 100, 그 밖 1)
    exchange_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))  # 기준 단위당 원 (예: 100엔 = 905.12). 원화는 NULL
    krw_goods_total: Mapped[int | None] = mapped_column(BigInteger)  # 품목 원화 합계 스냅샷 (승인 때 계산·저장)
    freight_terms: Mapped[str | None]  # 운송비 조건 코드 (공급업체 기본값 복사)
    freight_amount: Mapped[int | None] = mapped_column(BigInteger)  # 운송비 (원, 내부 전용)
    extra_costs: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), default=list)  # 부대비용 [{name, amount}] (원, 내부 전용)
    special_terms: Mapped[str | None]  # 특약 (공급업체 기본값 복사, 공급업체와 합의하는 글)


class PurchaseOrderItem(CompanyMixin, Base):
    """발주 품목: 발주서의 품목 한 줄. 입고 수량 칸은 없다(이력 합계로 계산)."""

    __tablename__ = "purchase_order_items"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "product_id", name="uq_po_items_order_product"),  # 한 발주서에 같은 품목 두 줄 금지
        CheckConstraint("quantity >= 1", name="ck_po_items_quantity"),  # 발주 수량은 1 이상
        CheckConstraint("unit_price >= 0", name="ck_po_items_unit_price"),  # 단가는 0 이상
        CheckConstraint("recommended_quantity >= 0", name="ck_po_items_recommended_quantity"),  # 추천 수량은 0 이상 (비어 있으면 통과)
        CheckConstraint(
            "(units_per_box IS NULL AND box_unit_price IS NULL AND fx_box_unit_price IS NULL) OR "
            "(units_per_box IS NOT NULL AND (box_unit_price IS NOT NULL OR fx_box_unit_price IS NOT NULL) "
            "AND units_per_box BETWEEN 1 AND 1000000 AND (box_unit_price IS NULL OR box_unit_price BETWEEN 0 AND 100000000) "
            "AND quantity % NULLIF(units_per_box, 0) = 0 AND quantity <= 1000000)",
            name="ck_po_items_box_snapshot",
        ),
        CheckConstraint(  # 원화 줄은 unit_price, 외화 줄은 fx 단가 하나만 (#267). 0 과 미입력을 섞지 않으려고 외화 줄의 원화 칸은 NULL
            "(unit_price IS NOT NULL AND fx_unit_price IS NULL AND fx_box_unit_price IS NULL) OR "
            "(unit_price IS NULL AND box_unit_price IS NULL AND (fx_unit_price IS NULL) <> (fx_box_unit_price IS NULL) "
            "AND (fx_box_unit_price IS NULL) = (units_per_box IS NULL))",
            name="ck_po_items_price_kind",
        ),
        CheckConstraint("fx_unit_price >= 0 AND fx_box_unit_price >= 0", name="ck_po_items_fx_price"),
        CheckConstraint("(units_per_box IS NULL) = (order_unit IS NULL)", name="ck_po_items_order_unit"),  # 발주단위 스냅샷은 박스 줄에만 (#185)
    )

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)  # 속한 발주서
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))  # 발주할 품목
    quantity: Mapped[int]  # 재고 기준 단위로 환산한 발주 수량
    unit_price: Mapped[int | None]  # 발주 당시 재고 단위 단가 (원). 외화 줄은 NULL (#267)
    units_per_box: Mapped[int | None]  # 발주 줄 작성 당시 박스 입수
    box_unit_price: Mapped[int | None]  # 발주 줄 작성 당시 박스당 단가
    order_unit: Mapped[str | None]  # 발주 줄 작성 당시 발주단위 이름 (마스터를 바꿔도 이 줄은 그대로, #185)
    min_order_units: Mapped[int | None]  # 발주 줄 작성 당시 최소 주문량(발주단위 수) 스냅샷 (#194)
    recommended_quantity: Mapped[int | None]  # 추천으로 만든 줄이면 당시 추천 수량
    recommendation_reason: Mapped[str | None]  # 당시 화면에 보인 이유 문장
    fx_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # 외화 줄의 재고 단위 단가 (발주서 통화, #267)
    fx_box_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))  # 외화 박스 줄의 발주단위 단가
