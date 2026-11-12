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
        CheckConstraint("(units_per_box IS NULL) = (order_unit IS NULL)", name="ck_products_order_unit"),  # 발주단위 이름은 박스 설정과 함께만 (#185)
    )

    sku: Mapped[str]  # 품목 코드
    name: Mapped[str]  # 품목명
    unit: Mapped[str]  # 단위 (개, 박스 등)
    unit_cost: Mapped[int]  # 구매 단가 (원 단위 정수)
    units_per_box: Mapped[int | None]  # 박스 입수
    box_unit_cost: Mapped[int | None]  # 박스당 구매 단가 (= 발주단위당 단가)
    order_unit: Mapped[str | None]  # 발주단위 이름 (예: 박스, PACK, BAG). 환산계수는 units_per_box (#185)
    color: Mapped[str | None]  # 옵션: 색상 (예: 검정). 같은 상품의 SKU를 구분하는 속성이고 연결에는 쓰지 않는다
    size: Mapped[str | None]  # 옵션: 사이즈 (예: M)
    spec: Mapped[str | None]  # 옵션: 규격 (예: 2L, 30롤)
    group_code: Mapped[str | None]  # 같은 상품끼리 묶는 그룹 코드 (대문자 저장)
    safety_stock: Mapped[int] = mapped_column(server_default="0")  # 안전재고, 기본 0
    default_supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))  # 기본 공급업체 (필수)
    is_active: Mapped[bool] = mapped_column(server_default=true())  # 기본 참, 삭제 대신 비활성
