"""품목과 발주 줄에 최소 주문량(min_order_units, 발주단위 수)을 더한다 (#194).

기존 행은 모두 NULL(제한 없음)로 두어 추천 결과가 바뀌지 않는다. 발주 줄의 값은 발주 당시 스냅샷이다.
"""

import sqlalchemy as sa
from alembic import op

revision = "e8b2d4f6a1c3"
down_revision = "d7a1c3e5f9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("products", sa.Column("min_order_units", sa.Integer(), nullable=True))  # 비어 있으면 제한 없음
    op.add_column("purchase_order_items", sa.Column("min_order_units", sa.Integer(), nullable=True))  # 발주 당시 값
    op.create_check_constraint("ck_products_min_order_units", "products", "min_order_units BETWEEN 1 AND 1000000")


def downgrade() -> None:
    op.drop_constraint("ck_products_min_order_units", "products", type_="check")
    op.drop_column("purchase_order_items", "min_order_units")
    op.drop_column("products", "min_order_units")
