from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, true  # 제약·외래키·참 값
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class Product(CompanyMixin, Base):
    """품목: 재고 칸은 없다. 현재고 = inventory_movements 합계(R2)."""

    __tablename__ = "products"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),  # 회사 안에서 SKU 중복 불가
        CheckConstraint("unit_cost >= 0", name="ck_products_unit_cost"),  # 단가는 0 이상
        CheckConstraint("safety_stock >= 0", name="ck_products_safety_stock"),  # 안전재고는 0 이상
        CheckConstraint(
            "(units_per_box IS NULL AND box_unit_cost IS NULL) OR "
            "(units_per_box IS NOT NULL AND box_unit_cost IS NOT NULL "
            "AND units_per_box BETWEEN 1 AND 1000000 AND box_unit_cost BETWEEN 0 AND 100000000)",
            name="ck_products_box_settings",
        ),
    )

    sku: Mapped[str]  # 품목 코드
    name: Mapped[str]  # 품목명
    unit: Mapped[str]  # 단위 (개, 박스 등)
    unit_cost: Mapped[int]  # 구매 단가 (원 단위 정수)
    units_per_box: Mapped[int | None]  # 박스 입수
    box_unit_cost: Mapped[int | None]  # 박스당 구매 단가
    safety_stock: Mapped[int] = mapped_column(server_default="0")  # 안전재고, 기본 0
    default_supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))  # 기본 공급업체 (필수)
    is_active: Mapped[bool] = mapped_column(server_default=true())  # 기본 참, 삭제 대신 비활성
