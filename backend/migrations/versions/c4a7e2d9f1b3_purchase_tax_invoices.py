"""매입 세금계산서 수취 기록 표 purchase_tax_invoices 를 더한다 (#268). 추가형이라 기존 표는 바꾸지 않는다."""

import sqlalchemy as sa
from alembic import op

revision = "c4a7e2d9f1b3"
down_revision = "8d3b6e1f4a92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_tax_invoices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("invoice_number", sa.Text(), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("supply_amount", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount", sa.BigInteger(), nullable=False),
        sa.Column("memo", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("supply_amount >= 0 AND tax_amount >= 0", name="ck_purchase_tax_invoices_amounts"),
        sa.CheckConstraint(  # 취소 3칸은 같이 있거나 같이 비어 있다
            "(cancelled_at IS NULL AND cancelled_by IS NULL AND cancel_reason IS NULL) "
            "OR (cancelled_at IS NOT NULL AND cancelled_by IS NOT NULL AND cancel_reason IS NOT NULL)",
            name="ck_purchase_tax_invoices_cancel",
        ),
    )
    op.create_index("ix_purchase_tax_invoices_company_id", "purchase_tax_invoices", ["company_id"])
    op.create_index("ix_purchase_tax_invoices_order", "purchase_tax_invoices", ["company_id", "purchase_order_id", "id"])
    op.create_index(  # 취소하지 않은 번호만 유일 (취소한 번호는 다시 넣을 수 있다)
        "uq_purchase_tax_invoices_number", "purchase_tax_invoices", ["company_id", "supplier_id", "invoice_number"],
        unique=True, postgresql_where=sa.text("cancelled_at IS NULL"),
    )
    # Supabase 공개 API 차단 (#43 과 같은 방식). 앱은 표 소유자라 FORCE 없이 계속 읽고 쓴다
    op.execute("ALTER TABLE public.purchase_tax_invoices ENABLE ROW LEVEL SECURITY")
    for role in ("anon", "authenticated"):  # 롤이 없는 로컬·CI DB 에서는 건너뛴다
        op.execute(f"""
            DO $$ BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN
                    REVOKE ALL ON public.purchase_tax_invoices FROM {role};
                END IF;
            END $$;
        """)


def downgrade() -> None:
    op.drop_table("purchase_tax_invoices")  # 인덱스·제약·RLS 설정도 함께 지워진다
