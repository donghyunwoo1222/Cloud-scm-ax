"""멱등 키 표 idempotency_keys 를 더한다 (#190).

같은 Idempotency-Key 로 다시 온 입출고·정정·발주 입고 요청에 첫 응답을 그대로 돌려주려고 24시간 기억한다.
업무 데이터가 아니라서 만료된 행은 서버가 다음 요청 때 지운다.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f9c3e7a2b5d8"
down_revision = "e8b2d4f6a1c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("endpoint", sa.String(200), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),  # 처리 중에는 비어 있고 커밋 전에 채운다
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_idempotency_keys_company_id", "idempotency_keys", ["company_id"])
    op.create_index("uq_idempotency_company_endpoint_key", "idempotency_keys",
                    ["company_id", "endpoint", "idempotency_key"], unique=True)


def downgrade() -> None:
    op.drop_table("idempotency_keys")
