"""발주서 변경 이력 표 po_change_log 를 더한다 (#181).

DRAFT 수정·상태 변경 때 바뀐 칸마다 변경 전·후 값, 수정자, 시각, 사유를 한 행씩 쌓는다(추가 전용).
기존 발주서의 이력은 만들지 않는다(소급 복원 없음). 기존 데이터는 건드리지 않는다.
"""

import sqlalchemy as sa
from alembic import op

revision = "a1d5f3c7b9e2"
down_revision = "f9c3e7a2b5d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_change_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_po_change_log_company_id", "po_change_log", ["company_id"])
    op.create_index("ix_po_change_log_order", "po_change_log", ["company_id", "purchase_order_id", "id"])


def downgrade() -> None:
    op.drop_table("po_change_log")
