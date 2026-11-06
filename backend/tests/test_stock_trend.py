"""품목별 30일 마감 재고와 회사 분리를 API에서 검증한다."""

from datetime import date, timedelta

from tests.helpers import login_as
from tests.test_dashboard import TODAY, add_move, add_product


def test_stock_trend_uses_opening_balance_and_movement_dates(client, world, session, monkeypatch):
    today = date(2026, 11, 6)
    monkeypatch.setattr("app.api.stock.seoul_today", lambda: today)
    offset = (TODAY - today).days  # 기존 이력 준비 도구의 오늘을 고정 날짜에 맞춘다
    product = add_product(session, world, "a", "TREND")
    add_move(session, world, "a", product, "RECEIPT", "IN", 100, offset + 30)
    add_move(session, world, "a", product, "SALE", "OUT", 100, offset + 29)
    receipt = add_move(session, world, "a", product, "RECEIPT", "IN", 42, offset + 21)
    add_move(session, world, "a", product, "CORRECTION", "OUT", 2, offset + 21, reverses=receipt.id)
    add_move(session, world, "a", product, "SALE", "OUT", 10, offset + 21)
    add_move(session, world, "a", product, "ADJUSTMENT", "OUT", 30, offset)
    session.commit()
    login_as(client)

    response = client.get(f"/api/v1/stock/{product.id}/trend")
    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    days = data["days"]
    assert data["sku"] == "TREND" and data["unit"] == "개"
    assert len(days) == 30
    assert days[0] == {
        "day": (today - timedelta(days=29)).isoformat(),
        "closing_stock": 0, "received_quantity": 0, "reached_zero": True,
    }
    assert days[1]["closing_stock"] == 0 and not days[1]["reached_zero"]
    assert days[8]["closing_stock"] == 30 and days[8]["received_quantity"] == 40
    assert days[9]["closing_stock"] == 30 and days[9]["received_quantity"] == 0
    assert days[-1]["day"] == today.isoformat() and days[-1]["reached_zero"]
    assert days[-1]["closing_stock"] == client.get(f"/api/v1/stock/{product.id}").json()["data"]["current_stock"] == 0


def test_stock_trend_distinguishes_missing_history_and_scopes_products(client, world, session, monkeypatch):
    today = date(2026, 11, 6)
    monkeypatch.setattr("app.api.stock.seoul_today", lambda: today)
    empty = add_product(session, world, "a", "EMPTY")
    new = add_product(session, world, "a", "FIRST")
    foreign = add_product(session, world, "b", "FOREIGN")
    add_move(session, world, "a", new, "RECEIPT", "IN", 5, (TODAY - today).days)
    session.commit()
    login_as(client)
    url = "/api/v1/stock"
    assert client.get(f"{url}/{foreign.id}/trend").status_code == 404
    empty_days = client.get(f"{url}/{empty.id}/trend").json()["data"]["days"]
    assert all(day["closing_stock"] is None and not day["reached_zero"] for day in empty_days)
    new_days = client.get(f"{url}/{new.id}/trend").json()["data"]["days"]
    assert new_days[-2]["closing_stock"] is None
    assert new_days[-1]["closing_stock"] == 5 and new_days[-1]["received_quantity"] == 5
