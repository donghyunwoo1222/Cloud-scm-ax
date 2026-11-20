"""메일 발송 시도 이력 표 po_email_log 를 더하고, 옛 "마지막 발송" 기록을 한 행씩 옮겨 둔다 (#182).

추가형이다: 기존 칸(emailed_at·emailed_to·emailed_by)은 그대로 두고 지우지 않는다.
백필: emailed_at 이 있는 발주서마다 1행 (kind ORDER, result SENT, 시각은 그때의 emailed_at, with_link 는 모름 = NULL).
"""

import sqlalchemy as sa
from alembic import op

revision = "b2e6d9a4c7f1"
down_revision = "a1d5c7e9b3f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_email_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sent_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),  # 옛 백필 행만 비어 있을 수 있다
        sa.Column("to_address", sa.Text(), nullable=True),  # 옛 백필 행만 비어 있을 수 있다
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("failure_code", sa.Text(), nullable=True),
        sa.Column("with_link", sa.Boolean(), nullable=True),  # 옛 백필 행은 모름
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("kind IN ('ORDER', 'REMINDER')", name="ck_po_email_log_kind"),
        sa.CheckConstraint("result IN ('SENT', 'FAILED', 'UNSAVED')", name="ck_po_email_log_result"),
        sa.CheckConstraint(
            "(result = 'FAILED' AND failure_code IN ('AUTH', 'RECIPIENT_REFUSED', 'TIMEOUT', 'CONNECTION', 'OTHER')) "
            "OR (result <> 'FAILED' AND failure_code IS NULL)",
            name="ck_po_email_log_failure_code",
        ),
    )
    op.create_index("ix_po_email_log_company_id", "po_email_log", ["company_id"])
    op.create_index("ix_po_email_log_order", "po_email_log", ["company_id", "purchase_order_id", "id"])
    # 옛 기록 옮기기: 시각은 마이그레이션 시각이 아니라 그때의 emailed_at (오래된 것부터 넣어 id 순서 = 시간 순서)
    op.execute(
        "INSERT INTO po_email_log (company_id, purchase_order_id, kind, sent_by, to_address, result, with_link, created_at, updated_at) "
        "SELECT company_id, id, 'ORDER', emailed_by, emailed_to, 'SENT', NULL, emailed_at, emailed_at "
        "FROM purchase_orders WHERE emailed_at IS NOT NULL ORDER BY emailed_at, id"
    )


def downgrade() -> None:
    op.drop_table("po_email_log")  # 옛 기록은 emailed_* 칸에 그대로 있으므로 잃는 것은 새로 쌓인 시도 이력뿐
