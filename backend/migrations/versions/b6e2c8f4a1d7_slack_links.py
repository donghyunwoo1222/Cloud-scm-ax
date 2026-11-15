"""슬랙 연결 표 slack_links 를 더한다 (#197).

SCM 사용자 한 명과 슬랙 계정 하나를 잇는다. 웹에서 6자리 코드를 발급하고(해시만 저장, 10분) 슬랙 DM 으로 그 코드를 보내면 연결된다.
업무 데이터가 아닌 기술용 기록이라 해제하면 행을 지운다.
"""

import sqlalchemy as sa
from alembic import op

revision = "b6e2c8f4a1d7"
down_revision = "a3d7f1c9e2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "slack_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),  # 사용자당 한 행
        sa.Column("link_code_hash", sa.String(64), nullable=True),
        sa.Column("link_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("slack_team_id", sa.String(32), nullable=True),
        sa.Column("slack_user_id", sa.String(32), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("(slack_user_id IS NULL) = (linked_at IS NULL)", name="ck_slack_links_linked"),
        sa.CheckConstraint("(slack_user_id IS NULL) = (slack_team_id IS NULL)", name="ck_slack_links_team"),
    )
    op.create_index("ix_slack_links_company_id", "slack_links", ["company_id"])
    op.create_index("uq_slack_links_code_hash", "slack_links", ["link_code_hash"], unique=True,
                    postgresql_where=sa.text("link_code_hash IS NOT NULL"))  # 살아 있는 코드는 겹치지 않는다
    op.create_index("uq_slack_links_slack_user", "slack_links", ["slack_team_id", "slack_user_id"], unique=True,
                    postgresql_where=sa.text("slack_user_id IS NOT NULL"))  # 슬랙 계정 하나는 한 사람에게만


def downgrade() -> None:
    op.drop_table("slack_links")
