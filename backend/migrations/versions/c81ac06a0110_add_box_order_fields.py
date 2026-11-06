"""품목의 박스 설정과 발주 줄의 당시 조건을 저장한다 (#110)."""

import sqlalchemy as sa
from alembic import op

revision = "c81ac06a0110"
down_revision = "12379841aad2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 행은 두 칸 모두 NULL이므로 기존 재고 단위의 의미를 유지한다.
    op.add_column("products", sa.Column("units_per_box", sa.Integer(), nullable=True))
    op.add_column("products", sa.Column("box_unit_cost", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_products_box_settings", "products",
        "(units_per_box IS NULL AND box_unit_cost IS NULL) OR "
        "(units_per_box IS NOT NULL AND box_unit_cost IS NOT NULL "
        "AND units_per_box BETWEEN 1 AND 1000000 AND box_unit_cost BETWEEN 0 AND 100000000)",
    )
    op.add_column("purchase_order_items", sa.Column("units_per_box", sa.Integer(), nullable=True))
    op.add_column("purchase_order_items", sa.Column("box_unit_price", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_po_items_box_snapshot", "purchase_order_items",
        "(units_per_box IS NULL AND box_unit_price IS NULL) OR "
        "(units_per_box IS NOT NULL AND box_unit_price IS NOT NULL "
        "AND units_per_box BETWEEN 1 AND 1000000 AND box_unit_price BETWEEN 0 AND 100000000 "
        "AND quantity % NULLIF(units_per_box, 0) = 0 AND quantity <= 1000000)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_po_items_box_snapshot", "purchase_order_items", type_="check")
    op.drop_column("purchase_order_items", "box_unit_price")
    op.drop_column("purchase_order_items", "units_per_box")
    op.drop_constraint("ck_products_box_settings", "products", type_="check")
    op.drop_column("products", "box_unit_cost")
    op.drop_column("products", "units_per_box")
