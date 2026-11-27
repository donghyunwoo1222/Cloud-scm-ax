from sqlalchemy import text  # PostgreSQL 시스템 뷰를 조회한다.


def test_all_public_tables_have_row_level_security(engine):
    # 현재 DB에서 직접 찾으므로 새 테이블과 alembic_version도 자동으로 검사한다.
    with engine.connect() as connection:
        unprotected_tables = connection.scalars(
            text(
                """
                SELECT tablename
                FROM pg_catalog.pg_tables
                WHERE schemaname = 'public' AND rowsecurity = false
                ORDER BY tablename
                """
            )
        ).all()

    assert not unprotected_tables, f"RLS가 꺼진 public 테이블: {', '.join(unprotected_tables)}"