"""발주서에 메일 발송 기록 칸 3개를 더한다 (#158). 이력 표 없이 마지막 1건만 남긴다."""

import sqlalchemy as sa
from alembic import op

revision = "f2c6a9d4e8b1"
down_revision = "e5b1c8d3a7f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 모두 선택 칸: 기존 발주서와 메일 없이 "주문 완료 표시"한 발주서는 NULL 로 남는다
    op.add_column("purchase_orders", sa.Column("emailed_at", sa.DateTime(timezone=True), nullable=True))  # 마지막 발송 시각
    op.add_column("purchase_orders", sa.Column("emailed_to", sa.String(), nullable=True))  # 마지막 수신 주소
    op.add_column("purchase_orders", sa.Column("emailed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))  # 보낸 사람


def downgrade() -> None:
    op.drop_column("purchase_orders", "emailed_by")
    op.drop_column("purchase_orders", "emailed_to")
    op.drop_column("purchase_orders", "emailed_at")
