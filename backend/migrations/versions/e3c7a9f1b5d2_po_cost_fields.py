"""발주서 원가 칸 (#267 PR 1): 통화·환율·원화 스냅샷·운송비·부대비용·특약, 외화 단가, 공급업체 기본 조건.

모두 추가형이다. 기존 발주서는 원화(KRW)·기준 단위 1·부대비용 없음으로 읽히고, 승인한 적 있는 발주서는 원화 스냅샷을 줄 금액 합계로 채운다.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e3c7a9f1b5d2"
down_revision = "d5a9b3e7f2c4"
branch_labels = None
depends_on = None

CURRENCY_LIST = "('KRW', 'USD', 'EUR', 'JPY', 'CNY', 'VND')"  # po_money.CURRENCIES 와 같은 목록
FREIGHT_LIST = "('INCLUDED', 'BILLED', 'COLLECT', 'EXW', 'FOB', 'CIF', 'DDP')"  # 운송비 조건 코드

# 승인한 적 있는 발주서(approved_at 이 있다: 승인됨·발주함·입고 완료와 승인 뒤 취소)의 원화 스냅샷 = 줄 금액 합계.
# 기존 줄은 모두 원화라 박스 줄은 박스 수 × 박스 단가, 아니면 수량 × 단가 (purchase_orders.line_total 과 같은 식). 줄이 없으면 0
BACKFILL = (
    "UPDATE purchase_orders po SET krw_goods_total = COALESCE(("
    "SELECT SUM(CASE WHEN i.units_per_box IS NULL THEN i.quantity::bigint * i.unit_price "
    "ELSE (i.quantity / i.units_per_box)::bigint * i.box_unit_price END) "
    "FROM purchase_order_items i WHERE i.purchase_order_id = po.id), 0) "
    "WHERE po.approved_at IS NOT NULL"
)

OLD_BOX_CHECK = (
    "(units_per_box IS NULL AND box_unit_price IS NULL) OR "
    "(units_per_box IS NOT NULL AND box_unit_price IS NOT NULL "
    "AND units_per_box BETWEEN 1 AND 1000000 AND box_unit_price BETWEEN 0 AND 100000000 "
    "AND quantity % NULLIF(units_per_box, 0) = 0 AND quantity <= 1000000)"
)
NEW_BOX_CHECK = (
    "(units_per_box IS NULL AND box_unit_price IS NULL AND fx_box_unit_price IS NULL) OR "
    "(units_per_box IS NOT NULL AND (box_unit_price IS NOT NULL OR fx_box_unit_price IS NOT NULL) "
    "AND units_per_box BETWEEN 1 AND 1000000 AND (box_unit_price IS NULL OR box_unit_price BETWEEN 0 AND 100000000) "
    "AND quantity % NULLIF(units_per_box, 0) = 0 AND quantity <= 1000000)"
)
PRICE_KIND_CHECK = (
    "(unit_price IS NOT NULL AND fx_unit_price IS NULL AND fx_box_unit_price IS NULL) OR "
    "(unit_price IS NULL AND box_unit_price IS NULL AND (fx_unit_price IS NULL) <> (fx_box_unit_price IS NULL) "
    "AND (fx_box_unit_price IS NULL) = (units_per_box IS NULL))"
)


def upgrade() -> None:
    po = "purchase_orders"
    op.add_column(po, sa.Column("currency", sa.String(), server_default="KRW", nullable=False))
    op.add_column(po, sa.Column("rate_unit", sa.Integer(), server_default="1", nullable=False))
    op.add_column(po, sa.Column("exchange_rate", sa.Numeric(12, 2), nullable=True))
    op.add_column(po, sa.Column("krw_goods_total", sa.BigInteger(), nullable=True))
    op.add_column(po, sa.Column("freight_terms", sa.String(), nullable=True))
    op.add_column(po, sa.Column("freight_amount", sa.BigInteger(), nullable=True))
    op.add_column(po, sa.Column("extra_costs", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column(po, sa.Column("special_terms", sa.String(), nullable=True))
    op.execute(BACKFILL)  # 아래 CHECK 보다 먼저 채운다
    op.create_check_constraint("ck_purchase_orders_currency", po, f"currency IN {CURRENCY_LIST}")
    op.create_check_constraint("ck_purchase_orders_rate_unit", po, "rate_unit IN (1, 100)")
    op.create_check_constraint("ck_purchase_orders_exchange_rate", po,
                               "NOT (currency = 'KRW' AND exchange_rate IS NOT NULL) AND exchange_rate > 0")
    op.create_check_constraint("ck_purchase_orders_krw_goods_total", po, "approved_at IS NULL OR krw_goods_total IS NOT NULL")
    op.create_check_constraint("ck_purchase_orders_cost_amounts", po, "krw_goods_total >= 0 AND freight_amount >= 0")
    op.create_check_constraint("ck_purchase_orders_freight_terms", po, f"freight_terms IN {FREIGHT_LIST}")

    items = "purchase_order_items"
    op.add_column(items, sa.Column("fx_unit_price", sa.Numeric(14, 2), nullable=True))
    op.add_column(items, sa.Column("fx_box_unit_price", sa.Numeric(14, 2), nullable=True))
    op.alter_column(items, "unit_price", existing_type=sa.Integer(), nullable=True)  # 외화 줄은 원화 단가가 없다
    op.drop_constraint("ck_po_items_box_snapshot", items, type_="check")
    op.create_check_constraint("ck_po_items_box_snapshot", items, NEW_BOX_CHECK)
    op.create_check_constraint("ck_po_items_price_kind", items, PRICE_KIND_CHECK)
    op.create_check_constraint("ck_po_items_fx_price", items, "fx_unit_price >= 0 AND fx_box_unit_price >= 0")

    op.add_column("suppliers", sa.Column("default_currency", sa.String(), server_default="KRW", nullable=False))
    op.add_column("suppliers", sa.Column("default_freight_terms", sa.String(), nullable=True))
    op.add_column("suppliers", sa.Column("default_special_terms", sa.String(), nullable=True))
    op.create_check_constraint("ck_suppliers_default_currency", "suppliers", f"default_currency IN {CURRENCY_LIST}")
    op.create_check_constraint("ck_suppliers_default_freight_terms", "suppliers", f"default_freight_terms IN {FREIGHT_LIST}")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM purchase_order_items WHERE unit_price IS NULL LIMIT 1")).first():
        # 외화 줄을 지우면 발주 금액이 사라진다. 조용히 지우지 않고 멈춘다
        raise RuntimeError("외화 발주 줄이 있어 되돌릴 수 없습니다. 외화 발주서를 먼저 정리하세요.")
    for name in ("ck_suppliers_default_freight_terms", "ck_suppliers_default_currency"):
        op.drop_constraint(name, "suppliers", type_="check")
    for column in ("default_special_terms", "default_freight_terms", "default_currency"):
        op.drop_column("suppliers", column)

    items = "purchase_order_items"
    for name in ("ck_po_items_fx_price", "ck_po_items_price_kind", "ck_po_items_box_snapshot"):
        op.drop_constraint(name, items, type_="check")
    op.create_check_constraint("ck_po_items_box_snapshot", items, OLD_BOX_CHECK)
    op.alter_column(items, "unit_price", existing_type=sa.Integer(), nullable=False)
    op.drop_column(items, "fx_box_unit_price")
    op.drop_column(items, "fx_unit_price")

    po = "purchase_orders"
    for name in ("ck_purchase_orders_freight_terms", "ck_purchase_orders_cost_amounts", "ck_purchase_orders_krw_goods_total",
                 "ck_purchase_orders_exchange_rate", "ck_purchase_orders_rate_unit", "ck_purchase_orders_currency"):
        op.drop_constraint(name, po, type_="check")
    for column in ("special_terms", "extra_costs", "freight_amount", "freight_terms", "krw_goods_total",
                   "exchange_rate", "rate_unit", "currency"):
        op.drop_column(po, column)
