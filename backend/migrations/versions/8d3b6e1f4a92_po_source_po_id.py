"""발주서 복사 원본 번호 칸(source_po_id)을 추가한다 (#188)."""

import sqlalchemy as sa
from alembic import op

revision = "8d3b6e1f4a92"
down_revision = "273fc501ab6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 복사해 만든 발주서가 어느 발주서에서 왔는지 가리킨다. 기존 행은 비어 있다.
    op.add_column("purchase_orders", sa.Column("source_po_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "source_po_id")
