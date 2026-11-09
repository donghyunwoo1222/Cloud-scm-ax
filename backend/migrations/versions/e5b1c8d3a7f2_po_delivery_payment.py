"""발주서에 납품장소·지불조건 칸을 더한다 (#157)."""

import sqlalchemy as sa
from alembic import op

revision = "e5b1c8d3a7f2"
down_revision = "d4a9e7b2c6f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 모두 선택 칸이라 기존 발주서는 NULL 로 남는다 (문서에서는 납품장소가 회사 주소로 대신 나온다)
    op.add_column("purchase_orders", sa.Column("delivery_address", sa.String(200), nullable=True))
    op.add_column("purchase_orders", sa.Column("payment_terms", sa.String(200), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "payment_terms")
    op.drop_column("purchase_orders", "delivery_address")
