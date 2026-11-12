"""품목과 발주 줄에 발주단위 이름(order_unit)을 더한다 (#185).

환산계수는 기존 units_per_box 를 그대로 쓴다. 이미 박스 설정이 있는 품목·박스 발주 줄은 지금 화면에 보이는
"박스"로 채우고, 박스 설정이 없는 행은 NULL 로 둔다. 그 뒤에 "박스 설정과 이름은 함께 있거나 함께 없다" 제약을 건다.
기존 CHECK 가 units_per_box·box_unit_cost(box_unit_price)를 함께 있거나 함께 없게 막고 있어, 채운 뒤에는 위반 행이 생기지 않는다.
"""

import sqlalchemy as sa
from alembic import op

revision = "d7a1c3e5f9b2"
down_revision = "c4f8a2e6d9b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("order_unit", sa.String(), nullable=True))
    op.add_column("purchase_order_items", sa.Column("order_unit", sa.String(), nullable=True))
    # 기존 박스 품목·박스 발주 줄만 "박스"로 채운다 (입수 1인 박스 품목도 박스 설정이 있으므로 "박스")
    op.execute("UPDATE products SET order_unit = '박스' WHERE units_per_box IS NOT NULL")
    op.execute("UPDATE purchase_order_items SET order_unit = '박스' WHERE units_per_box IS NOT NULL")
    op.create_check_constraint("ck_products_order_unit", "products", "(units_per_box IS NULL) = (order_unit IS NULL)")
    op.create_check_constraint("ck_po_items_order_unit", "purchase_order_items", "(units_per_box IS NULL) = (order_unit IS NULL)")


def downgrade() -> None:
    op.drop_constraint("ck_po_items_order_unit", "purchase_order_items", type_="check")
    op.drop_constraint("ck_products_order_unit", "products", type_="check")
    op.drop_column("purchase_order_items", "order_unit")
    op.drop_column("products", "order_unit")
