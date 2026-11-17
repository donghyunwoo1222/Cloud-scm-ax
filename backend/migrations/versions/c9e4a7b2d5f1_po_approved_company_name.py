"""발주서에 승인 시점 회사명 칸을 더한다 (#263). 문서 도장이 회사명 변경과 상관없이 승인 때 이름으로 남게 한다."""

import sqlalchemy as sa
from alembic import op

revision = "c9e4a7b2d5f1"
down_revision = "b6e2c8f4a1d7"
branch_labels = None
depends_on = None

# 이미 승인된 발주서 채우기. 지금까지 회사명을 바꾸는 API 가 없었으므로 현재 회사명 = 승인 시점 회사명이다
BACKFILL = (
    "UPDATE purchase_orders po SET approved_company_name = c.name "
    "FROM companies c WHERE po.company_id = c.id AND po.approved_at IS NOT NULL"
)


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("approved_company_name", sa.String(), nullable=True))  # 승인 전 발주서는 NULL
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_column("purchase_orders", "approved_company_name")
