from datetime import date, datetime  # 날짜·시각 칸의 파이썬 타입

from sqlalchemy import (  # 제약·인덱스 도구
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    UniqueConstraint,
    text,
)
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
    ordered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # ORDERED로 바뀐 시각
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # RECEIVED로 바뀐 시각
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # CANCELLED로 바뀐 시각
    # 메일 발송 기록 (#158): 이력 표 없이 마지막 1건만 남긴다 (다시 보내면 덮어쓴다)
    emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 마지막 발송 시각 (메일 서버가 받은 시각, 공급업체 수신 확인 아님)
    emailed_to: Mapped[str | None]  # 마지막 수신 주소 (그때의 공급업체 이메일, 나중에 업체 이메일을 바꿔도 남는다)
    emailed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 마지막으로 보낸 사용자


class PurchaseOrderItem(CompanyMixin, Base):
    """발주 품목: 발주서의 품목 한 줄. 입고 수량 칸은 없다(이력 합계로 계산)."""

    __tablename__ = "purchase_order_items"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "product_id", name="uq_po_items_order_product"),  # 한 발주서에 같은 품목 두 줄 금지
        CheckConstraint("quantity >= 1", name="ck_po_items_quantity"),  # 발주 수량은 1 이상
        CheckConstraint("unit_price >= 0", name="ck_po_items_unit_price"),  # 단가는 0 이상
        CheckConstraint("recommended_quantity >= 0", name="ck_po_items_recommended_quantity"),  # 추천 수량은 0 이상 (비어 있으면 통과)
        CheckConstraint(
            "(units_per_box IS NULL AND box_unit_price IS NULL) OR "
            "(units_per_box IS NOT NULL AND box_unit_price IS NOT NULL "
            "AND units_per_box BETWEEN 1 AND 1000000 AND box_unit_price BETWEEN 0 AND 100000000 "
            "AND quantity % NULLIF(units_per_box, 0) = 0 AND quantity <= 1000000)",
            name="ck_po_items_box_snapshot",
        ),
    )

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)  # 속한 발주서
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))  # 발주할 품목
    quantity: Mapped[int]  # 재고 기준 단위로 환산한 발주 수량
    unit_price: Mapped[int]  # 발주 당시 재고 단위 단가 (원)
    units_per_box: Mapped[int | None]  # 발주 줄 작성 당시 박스 입수
    box_unit_price: Mapped[int | None]  # 발주 줄 작성 당시 박스당 단가
    recommended_quantity: Mapped[int | None]  # 추천으로 만든 줄이면 당시 추천 수량
    recommendation_reason: Mapped[str | None]  # 당시 화면에 보인 이유 문장
