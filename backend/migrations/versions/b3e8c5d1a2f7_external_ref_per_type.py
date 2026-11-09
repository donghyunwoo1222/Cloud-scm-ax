"""외부 번호(external_ref) 유일 제한에 이력 유형을 더한다 (#155).

판매 주문번호와 입고 번호가 같은 글자(예: 둘 다 "1001")여도 서로 막지 않게 한다.
"""

import sqlalchemy as sa
from alembic import op

revision = "b3e8c5d1a2f7"
down_revision = "a7d3f1c2b9e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("uq_movements_company_external_ref", table_name="inventory_movements")
    # (회사, 유형, 번호)로 유일: 같은 유형 안에서만 겹치지 못한다
    op.create_index(
        "uq_movements_company_type_external_ref", "inventory_movements", ["company_id", "movement_type", "external_ref"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_movements_company_type_external_ref", table_name="inventory_movements")
    op.create_index(
        "uq_movements_company_external_ref", "inventory_movements", ["company_id", "external_ref"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
