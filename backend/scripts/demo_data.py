"""시연 전용 생활용품 데이터를 한 번 생성한다. 실행 방법은 README를 참고한다."""

import argparse
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta

from sqlalchemy import URL, create_engine, make_url, select, text
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session

from app.auth.security import MIN_PASSWORD_LENGTH, hash_password
from app.clock import SEOUL, seoul_today
from app.config import settings
from app.models import (
    Company,
    PoChangeLog,
    PoEmailLog,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.services.stock import register_movement, register_movements
from scripts.seed import REDIRECT_ENV_VARS, check_seed_allowed

COMPANY_NAME = "온새미 생활유통 (시연 전용)"
AUTHOR_EMAIL = "history@scm-demo.invalid"
ACCOUNT_EMAILS = {"ADMIN": "admin@scm-demo.invalid", "STAFF": "staff@scm-demo.invalid"}


def check_demo_allowed(
    app_env: str, url: URL, environ: Mapping[str, str],
) -> str | None:
    """연결 전에 하나의 명시된 PostgreSQL 호스트만 허용한다."""
    host = url.host
    if url.drivername != "postgresql+psycopg" or not host or not re.fullmatch(r"[a-zA-Z0-9.:-]+", host):
        return "DATABASE_URL에 postgresql+psycopg 드라이버와 단일 DB 호스트를 지정하세요."
    if not url.database or not re.fullmatch(r"[a-zA-Z0-9_-]+", url.database):
        return "DATABASE_URL에 명확한 DB 이름을 지정하세요."
    if url.database.startswith("scm_test_"):
        return "테스트 DB에는 시연 데이터를 넣지 않습니다."
    # dbname·hostaddr·service 등을 포함한 URL 옵션 전체와 libpq의 접속 대상 기본값을 막는다.
    if url.query or any(key in environ for key in (
        *REDIRECT_ENV_VARS, "PGPORT", "PGDATABASE", "PGSERVICEFILE", "PGSYSCONFDIR", "PGOPTIONS",
    )):
        return "DATABASE_URL의 쿼리 옵션과 PGHOST 등 접속 대상을 바꿀 수 있는 PG 환경변수를 제거하세요."
    if host != environ.get("ALLOW_DEMO_HOST"):
        return f"대상 DB 호스트를 허용하려면 ALLOW_DEMO_HOST={host}를 지정하세요."
    return check_seed_allowed(app_env, host, url.database, host)


def create_demo(db: Session, today: date, passwords: Mapping[str, str] | None = None) -> Company | None:
    """새 회사만 추가한다. 이미 생성됐으면 None을 반환하고, 확정은 호출자가 맡는다."""
    # 아직 잠글 회사 행이 없으므로 DB 안에서 스크립트끼리 같은 번호의 잠금을 쓴다.
    db.execute(text("SELECT pg_advisory_xact_lock(44044, 44)"))
    if db.scalar(select(Company.id).where(Company.name == COMPANY_NAME)) is not None:
        return None
    if db.scalar(select(User.id).where(User.email == AUTHOR_EMAIL)) is not None:
        return None  # 시연 회사의 이름을 바꾼 뒤에도 중복 생성하지 않는다.

    company = Company(name=COMPANY_NAME)
    db.add(company)
    db.flush()

    # 발주·입출고는 작성자 외래키가 필수다. 비활성이고 검증 가능한 비밀번호 해시도 없다.
    author = User(company_id=company.id, name="시연 이력 작성자", email=AUTHOR_EMAIL,
                  role="ADMIN", is_active=False, password_hash="disabled")
    db.add(author)
    if passwords is not None:
        for role, email in ACCOUNT_EMAILS.items():
            db.add(User(company_id=company.id, name="시연 관리자" if role == "ADMIN" else "시연 담당자",
                        role=role, email=email, password_hash=hash_password(passwords[role])))

    suppliers = [
        Supplier(company_id=company.id, name="다온 청소용품", lead_time_days=5, email="clean@scm-demo.invalid"),
        Supplier(company_id=company.id, name="누리 수납용품", lead_time_days=4, email="storage@scm-demo.invalid"),
    ]
    db.add_all(suppliers)
    db.flush()

    products = [
        Product(company_id=company.id, sku=sku, name=name, unit="개", unit_cost=cost, safety_stock=safety,
                default_supplier_id=suppliers[supplier].id)
        for supplier, sku, name, cost, safety in (
            (0, "CL-101", "극세사 청소포", 1250, 24),
            (0, "CL-102", "주방 수세미", 800, 25),
            (1, "ST-201", "접이식 정리함", 5400, 10),
            (1, "ST-202", "서랍 칸막이", 2300, 12),
            (1, "ST-203", "케이블 정리 클립", 650, 5),
            (1, "ST-204", "문걸이 수납 바구니", 3900, 8),
        )
    ]
    db.add_all(products)
    db.flush()

    def day(days_ago: int) -> date:
        return today - timedelta(days=days_ago)

    def at(days_ago: int, hour: int) -> datetime:
        return datetime.combine(day(days_ago), time(hour), SEOUL)

    # 정리 클립은 출시 직후, 수납 바구니는 판매 이력이 없는 품목이다.
    register_movements(
        company.id, db, author.id, movement_type="RECEIPT",
        rows=[{"product_id": product.id, "quantity": quantity, "movement_date": day(age)}
              for product, quantity, age in zip(products, (68, 42, 140, 100, 35, 40), (39, 39, 39, 39, 5, 39), strict=True)],
    )
    register_movements(
        company.id, db, author.id, movement_type="SALE", sales_channel="SMARTSTORE",
        rows=[{"product_id": product.id, "quantity": quantity, "movement_date": day(age)}
              for age in range(31, -1, -1)
              for product, quantity in zip(products[:4], (2, 1, 3, 1), strict=True)],
    )
    register_movement(
        company.id, db, author.id, product_id=products[0].id, movement_type="ADJUSTMENT",
        direction="OUT", quantity=3, movement_date=day(1), reason="재고 실사에서 파손품 3개 확인",
    )

    # (상태, 작성일 전, 납기일 전, 입고일 전, 품목별 (품목 번호, 발주량, 원화 단가, 입고량)).
    # 부분 입고는 ORDERED를 유지한다. 직전 완료 발주와 비교하면 초안의 단가는 25% 상승, 20% 하락한다.
    scenarios = (
        ("RECEIVED", 22, 15, 15, ((0, 12, 1000, 12), (1, 8, 1000, 8))),
        ("CANCELLED", 16, 9, None, ((2, 20, 5400, 0),)),
        ("ORDERED", 10, 2, 3, ((3, 24, 2300, 10),)),
        ("ORDERED", 7, 0, None, ((2, 30, 5400, 0),)),
        ("DRAFT", 0, -5, None, ((0, 30, 1250, 0), (1, 40, 800, 0))),
    )
    suppliers_by_id = {supplier.id: supplier for supplier in suppliers}
    for status, age, due, receipt, lines in scenarios:
        supplier = suppliers_by_id[products[lines[0][0]].default_supplier_id]
        approved = at(age, 10) if status != "DRAFT" else None
        ordered = at(age, 11) if approved else None
        order = PurchaseOrder(
            company_id=company.id, supplier_id=supplier.id, po_number=f"PO-{day(age):%Y%m%d}-001",
            status=status, due_date=day(due), created_by=author.id, created_at=at(age, 9),
            approved_by=author.id if approved else None, approved_at=approved,
            approved_company_name=company.name if approved else None,
            krw_goods_total=sum(qty * price for _, qty, price, _ in lines) if approved else None,
            ordered_at=ordered, received_at=at(receipt, 14) if status == "RECEIVED" else None,
            cancelled_at=at(age - 1, 10) if status == "CANCELLED" else None,
        )
        db.add(order)
        db.flush()

        for product_index, quantity, price, received in lines:
            item = PurchaseOrderItem(company_id=company.id, purchase_order_id=order.id,
                                     product_id=products[product_index].id, quantity=quantity, unit_price=price)
            db.add(item)
            if received:
                db.flush()
                register_movement(
                    company.id, db, author.id, product_id=item.product_id, movement_type="RECEIPT", direction="IN",
                    quantity=received, movement_date=day(receipt), purchase_order_item_id=item.id,
                )
        if approved:
            # 시연 시각을 재현한다. 메일 서버에 연결하지 않고 발송 성공 기록만 저장한다.
            order.emailed_at, order.emailed_to, order.emailed_by = ordered, supplier.email, author.id
            db.add(PoEmailLog(company_id=company.id, purchase_order_id=order.id, kind="ORDER", result="SENT",
                              sent_by=author.id, to_address=supplier.email, with_link=False, created_at=ordered))
            changes = [("DRAFT", "APPROVED", approved), ("APPROVED", "ORDERED", ordered)]
            if status in ("RECEIVED", "CANCELLED"):
                changes.append(("ORDERED", status, order.received_at or order.cancelled_at))
            for before, after, changed_at in changes:
                db.add(PoChangeLog(company_id=company.id, purchase_order_id=order.id, field="status",
                                   old_value=before, new_value=after, changed_by=author.id, created_at=changed_at,
                                   reason="공급업체 생산 일정 변경" if after == "CANCELLED" else None))
    return company


def main() -> None:
    parser = argparse.ArgumentParser(description="시연 전용 생활용품 데이터 생성")
    parser.add_argument("--with-accounts", action="store_true", help="관리자·담당자 로그인 계정도 생성")
    args = parser.parse_args()

    try:
        url = make_url(settings.database_url)
    except (ArgumentError, ValueError):
        raise SystemExit("DATABASE_URL 형식을 확인하세요.") from None
    if reason := check_demo_allowed(settings.app_env, url, os.environ):
        raise SystemExit(reason)

    passwords = None
    if args.with_accounts:
        passwords = {}
        for role in ACCOUNT_EMAILS:
            key = f"DEMO_{role}_PASSWORD"
            password = os.environ.get(key, "")
            if len(password) < MIN_PASSWORD_LENGTH:
                raise SystemExit(f"{key}에 {MIN_PASSWORD_LENGTH}자 이상의 비밀번호를 지정하세요.")
            passwords[role] = password

    engine = create_engine(url, isolation_level="READ COMMITTED")
    with Session(engine) as db, db.begin():
        if create_demo(db, seoul_today(), passwords) is None:
            raise SystemExit("시연 회사가 이미 있습니다. 기존 데이터를 그대로 두고 중단합니다.")
    print(f"{COMPANY_NAME} 데이터를 생성했습니다 (DB: {url.database}).")


if __name__ == "__main__":
    main()
