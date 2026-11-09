"""입출고 이력에 외부 주문번호(external_ref) 칸과 회사별 유일 제한을 더한다 (#154)."""

import sqlalchemy as sa
from alembic import op

revision = "a7d3f1c2b9e4"
down_revision = "c81ac06a0110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기존 행은 NULL(외부 주문번호 없음)이라 아무것도 바뀌지 않는다.
    op.add_column("inventory_movements", sa.Column("external_ref", sa.String(100), nullable=True))
    # 값이 있는 행끼리만 회사+값이 겹치지 못한다 (직접 입력한 이력은 NULL 이라 제한을 받지 않는다).
    op.create_index(
        "uq_movements_company_external_ref", "inventory_movements", ["company_id", "external_ref"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_movements_company_external_ref", table_name="inventory_movements")
    op.drop_column("inventory_movements", "external_ref")
