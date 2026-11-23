"""안내 챗봇 일별 통계 표 chat_daily_stats 를 더한다 (#199). 12번째 표.

회사 하나 × 서울 날짜 하루 = 한 행. 숫자만 저장하고 질문·답변 글은 저장하지 않는다.
새 표만 더하는 추가형이라 기존 데이터는 바뀌지 않는다.
"""

import sqlalchemy as sa
from alembic import op

revision = "c4f8a2d6e1b3"
down_revision = "b2e6d9a4c7f1"
branch_labels = None
depends_on = None

COUNTERS = ("requests", "answered", "not_found", "data_question", "failed", "blocked_pii", "limited")  # 정수 칸 (tokens_in 은 큰 정수)


def upgrade() -> None:
    op.create_table(
        "chat_daily_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        *(sa.Column(name, sa.Integer(), server_default="0", nullable=False) for name in COUNTERS),
        sa.Column("tokens_in", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("company_id", "day", name="uq_chat_daily_stats_company_day"),
        *(sa.CheckConstraint(f"{name} >= 0", name=f"ck_chat_daily_stats_{name}") for name in (*COUNTERS, "tokens_in")),
    )
    op.create_index("ix_chat_daily_stats_company_id", "chat_daily_stats", ["company_id"])


def downgrade() -> None:
    op.drop_table("chat_daily_stats")  # 통계 숫자만 사라진다(업무 데이터 영향 없음)
