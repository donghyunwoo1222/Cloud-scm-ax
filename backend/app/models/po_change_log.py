from sqlalchemy import ForeignKey, Index, Text  # 외래키, 인덱스, 길이 제한 없는 글자 칸
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class PoChangeLog(CompanyMixin, Base):
    """발주서 변경 이력(#181): 바뀐 칸 하나가 한 행. 추가만 하고 수정·삭제하지 않는다(재고 이력과 같은 원칙).

    시각은 행을 넣은 트랜잭션의 시작 시각(created_at)이라, 한 요청에서 쌓인 행은 모두 같은 시각이다.
    """

    __tablename__ = "po_change_log"  # DB 표 이름
    __table_args__ = (
        Index("ix_po_change_log_order", "company_id", "purchase_order_id", "id"),  # 발주서 하나의 이력을 최신순으로 읽는 조회용
    )

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))  # 어느 발주서의 이력인지
    field: Mapped[str] = mapped_column(Text)  # 바뀐 항목 (예: due_date, status, items[SKU-1].quantity, items[SKU-1])
    old_value: Mapped[str | None] = mapped_column(Text)  # 변경 전 값 (줄 추가·값이 없었던 칸은 비움)
    new_value: Mapped[str | None] = mapped_column(Text)  # 변경 후 값 (줄 삭제·값을 비운 칸은 비움)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 바꾼 사용자
    reason: Mapped[str | None] = mapped_column(Text)  # 사유 (취소 때만 입력, 선택)
