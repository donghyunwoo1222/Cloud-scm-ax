"""users 에 "비밀번호 변경 필요" 표시 칸을 더한다 (#169). 기존 계정은 거짓(강제하지 않음)으로 둔다."""

import sqlalchemy as sa
from alembic import op

revision = "a3d8f1c5b7e9"
down_revision = "f2c6a9d4e8b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 기본 거짓: 이미 있는 계정은 그대로 쓰고, 관리자가 새로 만든 직원만 코드에서 참으로 시작한다
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
