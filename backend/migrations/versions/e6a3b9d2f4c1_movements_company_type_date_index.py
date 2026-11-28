"""회사·유형·날짜 인덱스 (#357 판매 분석).

회사 전체의 기간 판매(SALE)·정정(CORRECTION) 합계가 회사 전체 이력을 훑지 않고 해당 유형·기간만 읽게 한다.
측정(이력 110만 줄, 한 회사 22만 줄): 90일 판매 집계 128ms → 40ms, 30일 112ms → 11ms. 발주 추천의 30일 순판매도 같은 쿼리를 쓴다.
"""
from alembic import op

revision = "e6a3b9d2f4c1"
down_revision = "d5f2a8c1e7b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_movements_company_type_date", "inventory_movements", ["company_id", "movement_type", "movement_date"])


def downgrade() -> None:
    op.drop_index("ix_movements_company_type_date", table_name="inventory_movements")
