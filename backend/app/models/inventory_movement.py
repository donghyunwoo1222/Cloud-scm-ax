from datetime import date  # 날짜 칸의 파이썬 타입

from sqlalchemy import (  # 제약·외래키·인덱스·DB 함수·글자 칸·SQL 조각
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸

# 입출고 이력 한 행 안에서 지켜야 할 규칙 (erd.md 의 chk_movement 그대로). 줄별 뜻:
# 수량 양수 / 입고는 IN / 출고 3종은 OUT / 판매엔 채널 필수 / 판매가 아니면 채널 비움 / 조정·정정엔 사유 필수
# / 정정만 원래 이력을 가리키고 정정은 반드시 가리킴 / 발주 연결은 입고와 그 정정에만
CHK_MOVEMENT = (
    "quantity > 0"
    " AND (movement_type <> 'RECEIPT' OR direction = 'IN')"
    " AND (movement_type NOT IN ('SALE', 'DISPOSAL', 'OTHER_OUT') OR direction = 'OUT')"
    " AND (movement_type <> 'SALE' OR sales_channel IS NOT NULL)"
    " AND (movement_type = 'SALE' OR sales_channel IS NULL)"
    " AND (movement_type NOT IN ('ADJUSTMENT', 'CORRECTION') OR reason IS NOT NULL)"
    " AND ((movement_type = 'CORRECTION') = (reverses_movement_id IS NOT NULL))"
    " AND (movement_type IN ('RECEIPT', 'CORRECTION') OR purchase_order_item_id IS NULL)"
)


class InventoryMovement(CompanyMixin, Base):
    """입출고 이력: 현재고의 유일한 근거. 추가만 하고 고치거나 지우지 않는다(R2)."""

    __tablename__ = "inventory_movements"  # DB 표 이름
    __table_args__ = (
        CheckConstraint(CHK_MOVEMENT, name="chk_movement"),  # 위 규칙 묶음
        CheckConstraint(
            "movement_type IN ('RECEIPT', 'SALE', 'DISPOSAL', 'OTHER_OUT', 'ADJUSTMENT', 'CORRECTION')",
            name="ck_movements_type",  # 이력 유형은 여섯 값 중 하나만
        ),
        CheckConstraint("direction IN ('IN', 'OUT')", name="ck_movements_direction"),  # 방향은 늘림·줄임 중 하나
        CheckConstraint(
            "sales_channel IN ('SMARTSTORE', 'OWN_MALL', 'OTHER')",  # 판매 채널 값 (비어 있으면 통과)
            name="ck_movements_sales_channel",
        ),
        Index("ix_movements_company_product_date", "company_id", "product_id", "movement_date"),  # 품목별 재고·기간 판매 조회용
        Index(
            "uq_movements_company_external_ref", "company_id", "external_ref",
            unique=True, postgresql_where=text("external_ref IS NOT NULL"),  # 값이 있을 때만 회사 안에서 유일 (파일 중복 반영 방지, #154)
        ),
    )

    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))  # 수량이 바뀐 품목
    movement_type: Mapped[str]  # RECEIPT·SALE·DISPOSAL·OTHER_OUT·ADJUSTMENT·CORRECTION
    direction: Mapped[str]  # IN(늘림) 또는 OUT(줄임)
    quantity: Mapped[int]  # 수량, 항상 양수 (늘고 줆은 direction으로)
    movement_date: Mapped[date] = mapped_column(server_default=func.current_date())  # 입출고가 일어난 날, 기본 오늘
    purchase_order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_order_items.id"), index=True  # 발주 입고면 연결한 발주 품목, 발주별 누적 입고량 조회용 인덱스
    )
    reverses_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_movements.id")  # 정정이 바로잡는 원래 이력 (같은 표를 가리킴)
    )
    sales_channel: Mapped[str | None]  # SMARTSTORE·OWN_MALL·OTHER, SALE일 때 필수
    reason: Mapped[str | None]  # 조정·정정 사유
    memo: Mapped[str | None]  # 메모
    external_ref: Mapped[str | None] = mapped_column(String(100))  # 가져오기 파일의 고유 주문번호 (직접 입력은 비움)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))  # 등록한 사용자
