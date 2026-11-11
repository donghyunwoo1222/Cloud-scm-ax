"""users 에 비밀번호 재설정 링크 칸 2개를 더한다 (#170). 표는 늘리지 않고 사용자당 유효한 링크 1개만 둔다."""

import sqlalchemy as sa
from alembic import op

revision = "b7e2c9a4d1f6"
down_revision = "a3d8f1c5b7e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 둘 다 선택 칸: 링크를 요청하지 않은 계정은 NULL. 해시만 저장하고 원본 링크는 어디에도 남기지 않는다
    op.add_column("users", sa.Column("reset_token_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("reset_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_users_reset_token_hash", "users", ["reset_token_hash"])  # 링크로 사용자를 찾는다


def downgrade() -> None:
    op.drop_index("ix_users_reset_token_hash", table_name="users")
    op.drop_column("users", "reset_expires_at")
    op.drop_column("users", "reset_token_hash")
