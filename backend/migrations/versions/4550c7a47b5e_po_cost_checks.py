"""발주서 원가 CHECK 보강 (#267 PR 1 리뷰): 통화와 환율 기준 단위를 묶고, 승인한 외화 발주서는 환율을 비울 수 없게 한다.

e3c7a9f1b5d2 는 이미 main 에 들어가 고치지 않고, CHECK 만 바꾸고 더한다. 서비스는 이미 이 규칙대로 저장하므로 기존 행은 걸리지 않는다.
"""

from alembic import op

revision = "4550c7a47b5e"
down_revision = "e3c7a9f1b5d2"
branch_labels = None
depends_on = None

PO = "purchase_orders"
OLD_RATE_UNIT = "rate_unit IN (1, 100)"
NEW_RATE_UNIT = "rate_unit IN (1, 100) AND (currency IN ('JPY', 'VND')) = (rate_unit = 100)"  # po_money.CURRENCIES 의 기준 단위
FX_RATE_APPROVED = "approved_at IS NULL OR currency = 'KRW' OR exchange_rate IS NOT NULL"  # 승인한 외화 발주서는 환율이 있다


def upgrade() -> None:
    op.drop_constraint("ck_purchase_orders_rate_unit", PO, type_="check")
    op.create_check_constraint("ck_purchase_orders_rate_unit", PO, NEW_RATE_UNIT)
    op.create_check_constraint("ck_purchase_orders_fx_rate_approved", PO, FX_RATE_APPROVED)


def downgrade() -> None:
    op.drop_constraint("ck_purchase_orders_fx_rate_approved", PO, type_="check")
    op.drop_constraint("ck_purchase_orders_rate_unit", PO, type_="check")
    op.create_check_constraint("ck_purchase_orders_rate_unit", PO, OLD_RATE_UNIT)
