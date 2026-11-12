"""관리자 로그인 메일 인증코드(OTP) 칸을 users 에 더한다 (#179).

코드 원문은 저장하지 않고 HMAC 해시만 둔다. 기존 관리자는 이 마이그레이션이 실행된 시각부터 14일 동안
코드 없이 로그인할 수 있다(유예). 신규·승격 관리자는 유예 칸이 비어 있어 처음부터 코드를 거친다.
"""

import sqlalchemy as sa
from alembic import op

revision = "a3d7f1c9e2b4"
down_revision = "f9c3e7a2b5d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("otp_code_hash", sa.String(), nullable=True))
    op.add_column("users", sa.Column("otp_sent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("otp_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("otp_resends", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("otp_grace_until", sa.DateTime(timezone=True), nullable=True))
    # 유예 시작 = 이 마이그레이션이 실행되는 시각(배포 시각). 기존 관리자에게만 14일을 준다
    op.execute("UPDATE users SET otp_grace_until = now() + interval '14 days' WHERE role = 'ADMIN'")


def downgrade() -> None:
    for column in ("otp_grace_until", "otp_resends", "otp_attempts", "otp_sent_at", "otp_code_hash"):
        op.drop_column("users", column)
