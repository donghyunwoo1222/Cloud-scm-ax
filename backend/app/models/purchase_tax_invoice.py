from datetime import date, datetime  # 발행일, 취소 시각

from sqlalchemy import (  # 칸 종류·제약·인덱스
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class PurchaseTaxInvoice(CompanyMixin, Base):
    """매입 세금계산서 수취 기록(#268): 공급업체에게 받은 계산서 한 장이 한 행. 내부 전용(공급업체 문서에 나가지 않는다).

    삭제하지 않는다. 잘못 넣은 건은 취소 3칸(cancelled_at·cancelled_by·cancel_reason)을 채워 합계에서 뺀다.
    합계(공급가액 + 세액)는 저장하지 않고 응답에서 계산한다(두 값과 어긋날 일이 없게).
    """

    __tablename__ = "purchase_tax_invoices"  # DB 표 이름
    __table_args__ = (
        Index("ix_purchase_tax_invoices_order", "company_id", "purchase_order_id", "id"),  # 발주서 하나의 계산서 목록
        Index(  # 같은 회사·같은 공급업체에서 취소하지 않은 번호는 하나만 (취소한 번호는 다시 넣을 수 있다)
            "uq_purchase_tax_invoices_number", "company_id", "supplier_id", "invoice_number",
            unique=True, postgresql_where=text("cancelled_at IS NULL"),
        ),
        CheckConstraint("supply_amount >= 0 AND tax_amount >= 0", name="ck_purchase_tax_invoices_amounts"),
        CheckConstraint(  # 취소 3칸은 같이 있거나 같이 비어 있다
            "(cancelled_at IS NULL AND cancelled_by IS NULL AND cancel_reason IS NULL) "
            "OR (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancel_reason IS NOT NULL)",
            name="ck_purchase_tax_invoices_cancel",
        ),
    )

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))  # 어느 발주서
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))  # 발주서의 공급업체 (번호 중복 검사용 복사)
    invoice_number: Mapped[str] = mapped_column(Text)  # 계산서 번호 (형식 강제 없음, 앞뒤 공백 제거 1~50자)
    issue_date: Mapped[date] = mapped_column(Date)  # 발행일
    supply_amount: Mapped[int] = mapped_column(BigInteger)  # 공급가액(원)
    tax_amount: Mapped[int] = mapped_column(BigInteger)  # 세액(원)
    memo: Mapped[str | None] = mapped_column(Text)  # 메모 (내부용)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 기록한 사용자
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # 취소 시각
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 취소한 사용자
    cancel_reason: Mapped[str | None] = mapped_column(Text)  # 취소 사유
