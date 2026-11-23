"""안내 챗봇 피드백 숫자 칸을 chat_daily_stats 에 더한다 (#199 PR4). 새 표 없음(12개 유지).

helpful·not_helpful: 기본 0 인 정수 칸. 기존 행은 모두 0 이라 아래 제약을 만족한다.
제약: 둘 다 0 이상, 합계는 그날 answered 이하(피드백 수가 답한 수를 넘지 못한다).
"""

import sqlalchemy as sa
from alembic import op

revision = "d5a9b3e7f2c4"
down_revision = "c4f8a2d6e1b3"
branch_labels = None
depends_on = None

TABLE = "chat_daily_stats"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("helpful", sa.Integer(), server_default="0", nullable=False))
    op.add_column(TABLE, sa.Column("not_helpful", sa.Integer(), server_default="0", nullable=False))
    op.create_check_constraint("ck_chat_daily_stats_helpful", TABLE, "helpful >= 0")
    op.create_check_constraint("ck_chat_daily_stats_not_helpful", TABLE, "not_helpful >= 0")
    op.create_check_constraint("ck_chat_daily_stats_feedback_le_answered", TABLE, "helpful + not_helpful <= answered")


def downgrade() -> None:
    op.drop_constraint("ck_chat_daily_stats_feedback_le_answered", TABLE, type_="check")
    op.drop_constraint("ck_chat_daily_stats_not_helpful", TABLE, type_="check")
    op.drop_constraint("ck_chat_daily_stats_helpful", TABLE, type_="check")
    op.drop_column(TABLE, "not_helpful")  # 피드백 숫자만 사라진다(업무 데이터 영향 없음)
    op.drop_column(TABLE, "helpful")
