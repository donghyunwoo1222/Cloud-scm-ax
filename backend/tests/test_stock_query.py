"""재고·이력 조회 API (#31) 테스트: GET /stock, GET /stock/{id}, GET /inventory-movements. 준비 데이터 world 는 conftest."""

from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product  # 표
from tests.helpers import login_as  # 공통 로그인

STOCK = "/api/v1/stock"  # 재고 경로
MOVES = "/api/v1/inventory-movements"  # 이력 경로


def add_product(session, world, key, sku, **fields):
    """품목 하나 (회사 key: a/b)."""
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=sku, unit="개", unit_cost=1000,
                default_supplier_id=world[f"{key}_supplier"].id, **fields)
    session.add(p)
    session.flush()  # id 받기
    return p


def add_move(session, world, key, product, mtype, direction, qty, day=None, reverses=None):
    """이력 한 줄을 표에 직접 넣는다 (조회만 시험하므로 등록 API 를 거치지 않는다)."""
    m = InventoryMovement(
        company_id=world[f"{key}_company"].id, product_id=product.id, created_by=world[f"{key}_staff"].id,
        movement_type=mtype, direction=direction, quantity=qty, movement_date=day or seoul_today(),
        sales_channel="OWN_MALL" if mtype == "SALE" else None,
        reason="사유" if mtype in ("ADJUSTMENT", "CORRECTION") else None, reverses_movement_id=reverses,
    )
    session.add(m)
    session.flush()
    return m


@pytest.fixture
def data(world, session):
    """A: 활성 품목 p1(입고·출고·조정·정정 섞임), p2(이력 없음), 비활성 p3. B: 품목 b1."""
    p1 = add_product(session, world, "a", "P1", safety_stock=7)
    p2 = add_product(session, world, "a", "P2")
    p3 = add_product(session, world, "a", "P3", is_active=False)
    b1 = add_product(session, world, "b", "B1")
    today = seoul_today()
    receipt = add_move(session, world, "a", p1, "RECEIPT", "IN", 100, today - timedelta(days=10))
    sale = add_move(session, world, "a", p1, "SALE", "OUT", 30, today - timedelta(days=5))
    add_move(session, world, "a", p1, "ADJUSTMENT", "OUT", 3, today - timedelta(days=4))
    add_move(session, world, "a", p1, "ADJUSTMENT", "IN", 2, today - timedelta(days=3))
    corr = add_move(session, world, "a", p1, "CORRECTION", "IN", 10, sale.movement_date, reverses=sale.id)  # 판매 30 중 10 정정
    add_move(session, world, "a", p3, "RECEIPT", "IN", 4)
    add_move(session, world, "b", b1, "RECEIPT", "IN", 999)
    session.commit()
    return {"p1": p1, "p2": p2, "p3": p3, "b1": b1, "receipt": receipt, "sale": sale, "corr": corr}


def by_sku(response):
    return {r["sku"]: r for r in response.json()["data"]}


# ----- 재고 -----
def test_stock_equals_movement_sum(client, world, data):
    """100 − 30 − 3 + 2 + 10(정정) = 79. 이력 없는 품목은 0. 안전재고도 함께."""
    login_as(client)
    rows = by_sku(client.get(STOCK))
    assert rows["P1"]["current_stock"] == 79 and rows["P1"]["safety_stock"] == 7
    assert rows["P2"]["current_stock"] == 0
    assert client.get(f"{STOCK}/{data['p1'].id}").json()["data"]["current_stock"] == 79


def test_stock_hides_inactive_by_default(client, world, data):
    login_as(client)
    assert set(by_sku(client.get(STOCK))) == {"P1", "P2"}  # 비활성 P3 숨김
    rows = by_sku(client.get(STOCK, params={"include_inactive": "true"}))
    assert set(rows) == {"P1", "P2", "P3"} and rows["P3"]["current_stock"] == 4
    assert client.get(f"{STOCK}/{data['p3'].id}").status_code == 200  # 상세는 비활성도 조회 가능


def test_stock_other_company_not_visible(client, world, data):
    login_as(client)
    assert "B1" not in by_sku(client.get(STOCK, params={"include_inactive": "true"}))
    assert client.get(f"{STOCK}/{data['b1'].id}").status_code == 404  # 다른 회사 품목은 없는 것처럼
    login_as(client, "staff@b.test")
    assert by_sku(client.get(STOCK))["B1"]["current_stock"] == 999  # 회사 B 는 자기 것만


def test_stock_paging(client, world, data):
    login_as(client)
    body = client.get(STOCK, params={"page_size": 1, "page": 2}).json()
    assert body["meta"] == {"page": 2, "page_size": 1, "total": 2} and len(body["data"]) == 1
    for size in (0, 101):
        assert client.get(STOCK, params={"page_size": size}).status_code == 422


def test_stock_requires_login(client, world, data):
    assert client.get(STOCK).status_code == 401
    assert client.get(MOVES).status_code == 401


# ----- 이력 -----
def test_movements_latest_first_and_correction_link(client, world, data):
    """입출고일 최신순(같은 날은 나중 등록 먼저). 정정 행은 reverses_movement_id 를 가진다."""
    login_as(client)
    body = client.get(MOVES, params={"product_id": data["p1"].id}).json()
    types = [m["movement_type"] for m in body["data"]]
    assert types == ["ADJUSTMENT", "ADJUSTMENT", "CORRECTION", "SALE", "RECEIPT"]  # -3일, -4일, 정정(-5일, 판매보다 나중), 판매(-5일), 입고(-10일)
    corr = body["data"][2]
    assert corr["reverses_movement_id"] == data["sale"].id and corr["id"] == data["corr"].id
    assert body["data"][3]["reverses_movement_id"] is None
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 5}


def test_movements_filters(client, world, data):
    login_as(client)
    today = seoul_today()
    p1 = data["p1"].id
    assert client.get(MOVES, params={"product_id": p1, "movement_type": "SALE"}).json()["meta"]["total"] == 1
    assert client.get(MOVES, params={"movement_type": "CORRECTION"}).json()["meta"]["total"] == 1
    got = client.get(MOVES, params={"product_id": p1, "date_from": (today - timedelta(days=5)).isoformat(),
                                    "date_to": (today - timedelta(days=4)).isoformat()}).json()
    assert got["meta"]["total"] == 4 - 1  # 판매·정정(-5일)과 조정(-4일). 양 끝 포함
    assert client.get(MOVES, params={"date_from": today.isoformat(), "date_to": (today - timedelta(days=1)).isoformat()}).status_code == 422
    assert client.get(MOVES, params={"movement_type": "BOGUS"}).status_code == 422
    assert client.get(MOVES, params={"product_id": data["p3"].id}).json()["meta"]["total"] == 1  # 비활성 품목의 이력도 볼 수 있다


def test_movements_other_company_not_visible(client, world, data):
    login_as(client)
    assert client.get(MOVES, params={"product_id": data["b1"].id}).json()["meta"]["total"] == 0  # 남의 품목 id 로 걸러도 빈 목록
    assert all(m["product_id"] != data["b1"].id for m in client.get(MOVES).json()["data"])
    assert client.get(MOVES).json()["meta"]["total"] == 6  # 회사 A 이력만 (B 의 999 입고 제외)


def test_movements_paging_bounds(client, world, data):
    login_as(client)
    for size in (0, 101):
        assert client.get(MOVES, params={"page_size": size}).status_code == 422
    assert client.get(MOVES, params={"page_size": 100}).status_code == 200
    assert client.get(MOVES, params={"page_size": 2, "page": 2}).json()["data"] != []


def test_movements_include_product_name_and_sku(client, world, data):
    """이력 응답에 품목 SKU·이름이 들어 있다 (화면이 품목 번호 대신 이름을 보여주려고)."""
    login_as(client)
    row = client.get(MOVES, params={"product_id": data["p1"].id}).json()["data"][0]
    assert row["product_sku"] == "P1" and row["product_name"] == "P1"
