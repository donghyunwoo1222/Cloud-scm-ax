"""가입 제한 카운터와 만료 행 정리용 인덱스를 추가한다."""

import sqlalchemy as sa
from alembic import op

revision = "273fc501ab6d"
down_revision = "6c2f0a9e4b17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("signup_rate_limits",
                    sa.Column("ip_hash", sa.LargeBinary(), primary_key=True),
                    sa.Column("attempts", sa.Integer(), nullable=False),
                    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_signup_rate_limits_expires_at", "signup_rate_limits", ["expires_at"])
    op.execute("ALTER TABLE public.signup_rate_limits ENABLE ROW LEVEL SECURITY")
    for role in ("anon", "authenticated"):  # Supabase 공개 롤에는 테이블 권한도 주지 않는다.
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE ALL ON public.signup_rate_limits FROM {role};
                END IF;
            END $$;
        """)


def downgrade() -> None:
    op.drop_table("signup_rate_limits")
