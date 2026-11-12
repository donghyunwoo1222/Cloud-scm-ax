"""products 에 옵션 칸 4개(색상·사이즈·규격·그룹 코드)를 더한다 (#178). 모두 선택 칸이라 기존 품목은 NULL 로 남는다."""

import sqlalchemy as sa
from alembic import op

revision = "c4f8a2e6d9b3"
down_revision = "b7e2c9a4d1f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable 추가만 한다: 기존 행을 고치지 않고, 옵션이 없는 품목은 응답에서 null 로 내려간다
    op.add_column("products", sa.Column("color", sa.String(), nullable=True))
    op.add_column("products", sa.Column("size", sa.String(), nullable=True))
    op.add_column("products", sa.Column("spec", sa.String(), nullable=True))
    op.add_column("products", sa.Column("group_code", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "group_code")
    op.drop_column("products", "spec")
    op.drop_column("products", "size")
    op.drop_column("products", "color")
