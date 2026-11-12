"""발주단위 이름(order_unit)과 환산계수(unit_factor = units_per_box) 테스트 (#185). 준비 데이터 world(회사 A·B)는 conftest."""

import pytest  # 테스트 도구
from sqlalchemy import select  # 조회문

from app.models import InventoryMovement  # 입출고 이력 표
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import add_product  # 회사 A·B 품목 준비

PRODUCTS = "/api/v1/products"  # 품목 경로
ORDERS = "/api/v1/purchase-orders"  # 발주 경로


def new_product(world, **override) -> dict:
    """품목 등록 본문 (1BOX = 100EA, 박스당 12,000원)."""
    body = {"sku": "BX-100", "name": "생수 100입", "unit": "EA", "unit_cost": 120,
            "units_per_box": 100, "box_unit_cost": 12_000, "default_supplier_id": world["a_supplier"].id}
    return {**body, **override}


def order(client, world, product_id, boxes) -> dict:
    """박스 수로 발주서 작성 → 응답 data."""
    r = client.post(ORDERS, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": product_id, "box_quantity": boxes}]})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


# ----- 1. 3BOX → 300EA 저장, 입고하면 재고 300 증가 (완료 기준 1) -----
def test_three_boxes_store_300_and_receipt_adds_300(client, world, session):
    login_as(client, "admin@a.test")
    pid = client.post(PRODUCTS, json=new_product(world, order_unit="BOX")).json()["data"]["id"]
    po = order(client, world, pid, 3)
    [line] = po["items"]
    assert (line["box_quantity"], line["quantity"], line["order_unit"], line["unit_factor"]) == (3, 300, "BOX", 100)
    assert line["line_total"] == 36_000  # 발주단위당 단가: 3BOX × 12,000원
    url = f"{ORDERS}/{po['id']}"
    assert client.post(f"{url}/approve").status_code == 200
    assert client.post(f"{url}/order").status_code == 200
    r = client.post(f"{url}/receipts", json={"items": [{"purchase_order_item_id": line["id"], "box_quantity": 3}]})
    assert r.status_code == 201, r.json()
    movement = session.scalar(select(InventoryMovement).where(InventoryMovement.purchase_order_item_id == line["id"]))
    assert movement.quantity == 300  # 이력은 기본단위(EA)로 기록
    stock = client.get(f"/api/v1/stock/{pid}").json()["data"]
    assert stock["current_stock"] == 300


# ----- 2. 마스터를 바꿔도 기존 발주서는 그대로 (완료 기준 2) -----
def test_snapshot_survives_master_change(client, world):
    login_as(client)
    pid = client.post(PRODUCTS, json=new_product(world, order_unit="BOX")).json()["data"]["id"]
    po = order(client, world, pid, 3)
    r = client.patch(f"{PRODUCTS}/{pid}", json={"order_unit": "PACK", "units_per_box": 120, "box_unit_cost": 15_000})
    assert r.status_code == 200 and r.json()["data"]["order_unit"] == "PACK"
    [line] = client.get(f"{ORDERS}/{po['id']}").json()["data"]["items"]
    assert (line["order_unit"], line["unit_factor"], line["quantity"], line["box_quantity"], line["line_total"]) == ("BOX", 100, 300, 3, 36_000)
    # DRAFT 를 다시 저장해도 당시 조건을 쓴다
    r = client.patch(f"{ORDERS}/{po['id']}", json={"items": [{"product_id": pid, "box_quantity": 2}]})
    [line] = r.json()["data"]["items"]
    assert (line["order_unit"], line["unit_factor"], line["quantity"], line["line_total"]) == ("BOX", 100, 200, 24_000)
    # 새 발주서는 바뀐 마스터 값을 쓴다 (업체당 DRAFT 는 1장이라 기존 것을 취소한 뒤 만든다)
    assert client.post(f"{ORDERS}/{po['id']}/cancel").status_code == 200
    [fresh] = order(client, world, pid, 1)["items"]
    assert (fresh["order_unit"], fresh["unit_factor"], fresh["quantity"], fresh["line_total"]) == ("PACK", 120, 120, 15_000)


# ----- 3. 환산계수 0·음수·소수는 422 -----
@pytest.mark.parametrize("factor", [0, -1, 2.5, "10"])
def test_invalid_factor_is_422(client, world, factor):
    login_as(client)
    assert client.post(PRODUCTS, json=new_product(world, units_per_box=factor)).status_code == 422


# ----- 4. 요청이 환산계수·발주단위를 보내면 (기존 규칙대로) 422 -----
@pytest.mark.parametrize("extra", [{"unit_factor": 1}, {"order_unit": "EA"}])
def test_order_request_cannot_send_factor_or_unit(client, world, session, extra):
    p = add_product(session, world, "BX", units_per_box=100, box_unit_cost=12_000, order_unit="BOX")
    session.commit()
    login_as(client)
    item = {"product_id": p.id, "box_quantity": 3, **extra}
    r = client.post(ORDERS, json={"supplier_id": world["a_supplier"].id, "items": [item]})
    assert r.status_code == 422  # 발주 줄은 모르는 칸을 거절한다 (extra="forbid", 기존 동작 유지)


# ----- 5. 발주단위 이름 규칙 (조건 1) -----
def test_box_settings_without_name_default_to_box(client, world):
    login_as(client)
    d = client.post(PRODUCTS, json=new_product(world)).json()["data"]  # order_unit 생략
    assert (d["order_unit"], d["unit_factor"]) == ("박스", 100)
    d = client.patch(f"{PRODUCTS}/{d['id']}", json={"order_unit": "  "}).json()["data"]  # 공백만 보내도
    assert d["order_unit"] == "박스"


def test_name_without_box_settings_is_422(client, world):
    login_as(client)
    body = new_product(world, units_per_box=None, box_unit_cost=None, order_unit="PACK")
    r = client.post(PRODUCTS, json=body)
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "order_unit"
    plain = client.post(PRODUCTS, json={**body, "order_unit": None}).json()["data"]
    assert client.patch(f"{PRODUCTS}/{plain['id']}", json={"order_unit": "PACK"}).status_code == 422


def test_clearing_box_settings_clears_name(client, world):
    login_as(client)
    pid = client.post(PRODUCTS, json=new_product(world, order_unit="PACK")).json()["data"]["id"]
    d = client.patch(f"{PRODUCTS}/{pid}", json={"units_per_box": None, "box_unit_cost": None}).json()["data"]
    assert (d["units_per_box"], d["order_unit"], d["unit_factor"]) == (None, "EA", 1)  # 응답은 재고 단위·1
    r = client.patch(f"{PRODUCTS}/{pid}", json={"units_per_box": 6, "box_unit_cost": 600})  # 다시 켜면 기본 이름
    assert r.json()["data"]["order_unit"] == "박스"


def test_name_over_20_chars_is_422(client, world):
    login_as(client)
    assert client.post(PRODUCTS, json=new_product(world, order_unit="가" * 21)).status_code == 422


# ----- 6. 다른 회사 품목 격리 -----
def test_other_company_box_product_is_isolated(client, world, session):
    b = add_product(session, world, "B-BX", key="b", units_per_box=10, box_unit_cost=500, order_unit="BAG")
    session.commit()
    login_as(client)
    assert client.get(f"{PRODUCTS}/{b.id}").status_code == 404
    assert client.patch(f"{PRODUCTS}/{b.id}", json={"order_unit": "BOX"}).status_code == 404
    r = client.post(ORDERS, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": b.id, "box_quantity": 1}]})
    assert r.status_code == 404


# ----- 7. 박스 설정이 없는 품목은 재고 단위·1 (기존 결과와 같음) -----
def test_plain_product_and_line_use_base_unit_and_factor_1(client, world, session):
    p = add_product(session, world, "PLAIN")
    session.commit()
    login_as(client)
    d = client.get(f"{PRODUCTS}/{p.id}").json()["data"]
    assert (d["order_unit"], d["unit_factor"], d["units_per_box"]) == ("개", 1, None)
    r = client.post(ORDERS, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": p.id, "quantity": 7, "unit_price": 800}]})
    [line] = r.json()["data"]["items"]
    assert (line["order_unit"], line["unit_factor"], line["quantity"], line["box_quantity"], line["line_total"]) == ("개", 1, 7, None, 5_600)
