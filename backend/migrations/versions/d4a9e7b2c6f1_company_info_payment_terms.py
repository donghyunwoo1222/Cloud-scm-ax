"""회사 정보 칸(사업자번호·대표자·주소·연락처)과 공급업체 지불조건을 더한다 (#156)."""

import sqlalchemy as sa
from alembic import op

revision = "d4a9e7b2c6f1"
down_revision = "b3e8c5d1a2f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 모두 선택 칸이라 기존 행은 NULL 로 남고 아무것도 바뀌지 않는다.
    op.add_column("companies", sa.Column("business_number", sa.String(10), nullable=True))
    op.add_column("companies", sa.Column("representative", sa.String(200), nullable=True))
    op.add_column("companies", sa.Column("address", sa.String(200), nullable=True))
    op.add_column("companies", sa.Column("phone", sa.String(200), nullable=True))
    op.add_column("suppliers", sa.Column("payment_terms", sa.String(200), nullable=True))
    # 사업자번호는 숫자 10자리만 (API 검사가 뚫려도 DB 가 막는 마지막 방어)
    op.create_check_constraint("ck_companies_business_number", "companies", "business_number ~ '^[0-9]{10}$'")


def downgrade() -> None:
    op.drop_constraint("ck_companies_business_number", "companies", type_="check")
    op.drop_column("suppliers", "payment_terms")
    for column in ("phone", "address", "representative", "business_number"):
        op.drop_column("companies", column)
