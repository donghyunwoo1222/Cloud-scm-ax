from collections import Counter, defaultdict
from datetime import date

import pytest
from sqlalchemy import func, make_url, select

from app.auth.security import verify_password
from app.models import (
    Company,
    InventoryMovement,
    PoChangeLog,
    PoEmailLog,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.schemas.purchase_orders import PriceCheck, PriceCheckItem
from app.services import price_alert, purchase_orders, recommendations, stock
from scripts import demo_data

TODAY = date(2026, 11, 27)
URL = make_url("postgresql+psycopg://scm@localhost:5547/scm_demo")


@pytest.mark.parametrize(("url", "app_env", "env"), [
    (URL, "development", {}),
    (URL, "development", {"ALLOW_DEMO_HOST": "127.0.0.1"}),
    (URL, "production", {"ALLOW_DEMO_HOST": "localhost"}),
    (URL.set(database="scm_test"), "development", {"ALLOW_DEMO_HOST": "localhost"}),
    (URL.set(database="scm_test_demo44"), "development", {"ALLOW_DEMO_HOST": "localhost"}),
    (URL.set(host="localhost,other"), "development", {"ALLOW_DEMO_HOST": "localhost,other"}),
    (URL.set(drivername="sqlite"), "development", {"ALLOW_DEMO_HOST": "localhost"}),
])
def test_requires_explicit_safe_target(url, app_env, env):
    assert demo_data.check_demo_allowed(app_env, url, env)


@pytest.mark.parametrize("key", ["host", "hostaddr", "service", "dbname", "port"])
def test_rejects_url_overrides_even_on_allowed_host(key):
    assert demo_data.check_demo_allowed("development", URL.set(query={key: "other"}), {"ALLOW_DEMO_HOST": "localhost"})


@pytest.mark.parametrize("key", ["PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGPORT", "PGDATABASE", "PGOPTIONS"])
def test_rejects_env_overrides_even_on_allowed_host(key):
    assert demo_data.check_demo_allowed("development", URL, {"ALLOW_DEMO_HOST": "localhost", key: "other"})


@pytest.mark.parametrize("host", ["localhost", "db", "demo-db.internal", "::1"])
def test_accepts_exact_explicit_host(host):
    assert demo_data.check_demo_allowed("development", URL.set(host=host), {"ALLOW_DEMO_HOST": host}) is None


def demo_rows(session, company, model):
    return list(session.scalars(select(model).where(model.company_id == company.id)))


def test_demo_history_and_repeat_run(session, world, monkeypatch):
    demo = demo_data.create_demo(session, TODAY)
    assert demo is not None and demo.name == demo_data.COMPANY_NAME
    session.commit()
    suppliers, products, orders, lines, movements, changes, emails, users = [
        demo_rows(session, demo, model) for model in (
            Supplier, Product, PurchaseOrder, PurchaseOrderItem, InventoryMovement, PoChangeLog, PoEmailLog, User,
        )
    ]
    assert [len(rows) for rows in (suppliers, products, orders, lines, movements, changes, emails, users)] == [
        2, 6, 5, 7, 138, 10, 4, 1,
    ]
    assert not users[0].is_active
    assert not verify_password("any password", users[0].password_hash)
    assert Counter(m.movement_type for m in movements) == {"RECEIPT": 9, "SALE": 128, "ADJUSTMENT": 1}
    assert (max(m.movement_date for m in movements) - min(m.movement_date for m in movements)).days == 39
    assert len({m.movement_date for m in movements if m.movement_type == "SALE"}) == 32
    assert {s.default_currency for s in suppliers} == {"KRW"}
    assert all(o.currency == "KRW" and o.exchange_rate is None for o in orders)
    assert all(i.fx_unit_price is None and i.fx_box_unit_price is None for i in lines)

    # 이력을 날짜순으로 쌓아 두 방향을 독립적으로 합산하고, 서버 현재고 및 중간 잔고도 확인한다.
    balance = defaultdict(int)
    for movement in sorted(movements, key=lambda m: (m.movement_date, m.id)):
        balance[movement.product_id] += movement.quantity if movement.direction == "IN" else -movement.quantity
        assert balance[movement.product_id] >= 0
    assert {p.sku: balance[p.id] for p in products} == {
        "CL-101": 13, "CL-102": 18, "ST-201": 44, "ST-202": 78, "ST-203": 35, "ST-204": 40,
    }
    assert all(stock.current_stock(demo.id, session, p.id) == balance[p.id] for p in products)

    received = purchase_orders.received_quantities(demo.id, session, [i.id for i in lines])
    states = Counter()
    for order in orders:
        ordered_qty = sum(i.quantity for i in lines if i.purchase_order_id == order.id)
        received_qty = sum(received.get(i.id, 0) for i in lines if i.purchase_order_id == order.id)
        assert 0 <= received_qty <= ordered_qty
        assert (received_qty == ordered_qty) == (order.status == "RECEIVED")
        if order.status in ("DRAFT", "CANCELLED"):
            assert received_qty == 0
        state = "PARTIAL" if order.status == "ORDERED" and received_qty else order.status
        states[state] += 1
    assert states == {"DRAFT": 1, "ORDERED": 1, "PARTIAL": 1, "RECEIVED": 1, "CANCELLED": 1}
    assert {e.purchase_order_id for e in emails} == {o.id for o in orders if o.emailed_at}
    assert {c.purchase_order_id for c in changes} == {e.purchase_order_id for e in emails}

    result = recommendations.list_recommendations(demo.id, session, TODAY)
    assert {p["product_sku"] for p in result["items"]} == {"CL-101", "CL-102"}
    assert {p["code"] for p in result["excluded"]} == {"INSUFFICIENT_DATA", "NO_SALES_30D"}
    draft = next(o for o in orders if o.status == "DRAFT")
    query = PriceCheck(supplier_id=draft.supplier_id, items=[
        PriceCheckItem(product_id=i.product_id, unit_price=i.unit_price)
        for i in lines if i.purchase_order_id == draft.id
    ])
    monkeypatch.setattr(price_alert.settings, "price_alert_percent", 10)
    alerts = price_alert.check(demo.id, session, query)
    assert {(a["alert"]["direction"], a["alert"]["percent"]) for a in alerts} == {("UP", 25), ("DOWN", 20)}

    # 이름을 바꿔도 내부 작성자 표시가 같은 회사의 재생성을 막는다.
    assert demo_data.create_demo(session, TODAY) is None
    demo.name = "시연 중 수정한 회사 이름"
    session.flush()
    assert demo_data.create_demo(session, TODAY) is None
    assert session.scalar(select(func.count()).select_from(Company)) == 3
    assert len(demo_rows(session, demo, InventoryMovement)) == 138
    assert world["a_company"].name == "회사A"
    assert world["b_supplier"].name == "B업체"


def test_demo_account_option_hashes_passwords(session):
    passwords = {"ADMIN": "admin-test-secret", "STAFF": "staff-test-secret"}
    demo = demo_data.create_demo(session, TODAY, passwords)
    session.flush()
    accounts = {u.role: u for u in demo_rows(session, demo, User) if u.is_active}
    assert set(accounts) == {"ADMIN", "STAFF"}
    for role, account in accounts.items():
        assert account.email == demo_data.ACCOUNT_EMAILS[role]
        assert account.password_hash != passwords[role]
        assert verify_password(passwords[role], account.password_hash)
