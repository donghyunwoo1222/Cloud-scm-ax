"""외부 번호(external_ref) 유일 제한에 품목(product_id)을 더한다 (#254).

주문 1건에 품목 여러 줄(같은 주문번호)인 파일도 줄마다 따로 반영되게 한다.
옛 키 (회사, 유형, 번호)가 이미 유일하므로 열을 하나 더한 새 키는 기존 행이 어길 수 없다.
"""
import sqlalchemy as sa
from alembic import op

revision = "d5f2a8c1e7b3"
down_revision = "c4a7e2d9f1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 같은 트랜잭션 안에서 새 인덱스를 먼저 만들고 옛 인덱스를 지운다 (중간에 유일 제한이 없는 순간이 없다)
    op.create_index(
        "uq_movements_company_type_ref_product", "inventory_movements",
        ["company_id", "movement_type", "external_ref", "product_id"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.drop_index("uq_movements_company_type_external_ref", table_name="inventory_movements")


def downgrade() -> None:
    # 새 규칙으로 같은 (회사, 유형, 번호)에 여러 품목이 들어갔다면 옛 유일 인덱스를 만들 수 없다.
    # 입출고 이력은 지울 수 없으므로(원칙 4) 개수를 세어 있으면 이유를 적고 멈춘다.
    conflicts = op.get_bind().scalar(sa.text(
        "SELECT count(*) FROM (SELECT 1 FROM inventory_movements WHERE external_ref IS NOT NULL "
        "GROUP BY company_id, movement_type, external_ref HAVING count(*) > 1) AS dup"
    ))
    if conflicts:
        raise RuntimeError(
            f"downgrade 불가(#254): 같은 주문번호에 품목이 둘 이상인 이력이 {conflicts}묶음 있어 "
            "옛 유일 인덱스(회사+유형+번호)를 만들 수 없습니다. 이력은 지울 수 없으므로 되돌리지 않습니다."
        )
    op.create_index(
        "uq_movements_company_type_external_ref", "inventory_movements", ["company_id", "movement_type", "external_ref"],
        unique=True, postgresql_where=sa.text("external_ref IS NOT NULL"),
    )
    op.drop_index("uq_movements_company_type_ref_product", table_name="inventory_movements")
