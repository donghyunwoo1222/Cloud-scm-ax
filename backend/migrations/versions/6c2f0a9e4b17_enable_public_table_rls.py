"""Supabase 공개 API에서 앱 테이블에 직접 접근하지 못하게 한다 (#43)."""

from alembic import op

revision = "6c2f0a9e4b17"
down_revision = "4550c7a47b5e"
branch_labels = None
depends_on = None

# 이 리비전 시점의 앱 테이블 12개와 Alembic 버전 테이블을 고정한다.
TABLES = (
    "companies",
    "users",
    "suppliers",
    "products",
    "purchase_orders",
    "purchase_order_items",
    "inventory_movements",
    "idempotency_keys",
    "po_change_log",
    "slack_links",
    "po_email_log",
    "chat_daily_stats",
    "alembic_version",
)


def upgrade() -> None:
    # 일반 테이블 소유자인 앱이 계속 읽고 쓸 수 있도록 FORCE는 적용하지 않는다.
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")

    # PostgreSQL 안에서 롤 존재 여부를 확인하므로 일반 로컬 DB와 오프라인 SQL 생성도 지원한다.
    tables = ", ".join(f"public.{table}" for table in TABLES)
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL PRIVILEGES ON TABLE {tables} FROM anon;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'authenticated') THEN
                REVOKE ALL PRIVILEGES ON TABLE {tables} FROM authenticated;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # RLS를 되돌린다. 이전 권한을 추측해서 공개 롤에 다시 부여하면 데이터가 노출될 수 있다.
    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} DISABLE ROW LEVEL SECURITY")