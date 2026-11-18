"""발주서에 공급업체 회신 칸 5개를 더하고 변경 이력의 changed_by 를 비울 수 있게 한다 (#265 PR1). 추가·완화만 한다."""

import sqlalchemy as sa
from alembic import op

revision = "a1d5c7e9b3f2"
down_revision = "c9e4a7b2d5f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("supplier_token_hash", sa.String(), nullable=True))  # 링크 토큰 해시 (내부 전용)
    op.add_column("purchase_orders", sa.Column("supplier_token_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("supplier_confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("purchase_orders", sa.Column("supplier_due_date", sa.Date(), nullable=True))  # 회신 납기
    op.add_column("purchase_orders", sa.Column("supplier_reply_count", sa.Integer(), server_default="0", nullable=False))  # 기존 행은 0
    op.create_unique_constraint("uq_purchase_orders_supplier_token_hash", "purchase_orders", ["supplier_token_hash"])
    op.alter_column("po_change_log", "changed_by", existing_type=sa.Integer(), nullable=True)  # 공급업체 회신은 사용자가 없다


def downgrade() -> None:
    op.alter_column("po_change_log", "changed_by", existing_type=sa.Integer(), nullable=False)
    op.drop_constraint("uq_purchase_orders_supplier_token_hash", "purchase_orders", type_="unique")
    for c in ("supplier_reply_count", "supplier_due_date", "supplier_confirmed_at", "supplier_token_expires_at", "supplier_token_hash"):
        op.drop_column("purchase_orders", c)
