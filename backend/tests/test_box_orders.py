"""박스 발주 API에서 수량, 금액, 당시 조건, 입고 이력을 확인한다 (#110)."""

from sqlalchemy import select

from app.models import InventoryMovement
from tests.helpers import login_as
from tests.test_recommendations import OLD, add_move, add_product

PRODUCTS = "/api/v1/products"
ORDERS = "/api/v1/purchase-orders"
RECOMMENDATIONS = "/api/v1/recommendations"


def test_box_recommendation_and_receipts(client, session, world):
    # 일평균 1 × (리드타임 5 + 보충 주기 14) + 안전재고 8 = 27개
    product = add_product(session, world, "BOX", safety_stock=8, units_per_box=10, box_unit_cost=10_005)
    add_move(session, world, product, "RECEIPT", "IN", 30, OLD)
    add_move(session, world, product, "SALE", "OUT", 30, 1)
    session.commit()
    login_as(client, "admin@a.test")

    [recommendation] = client.get(RECOMMENDATIONS).json()["data"]["items"]
    assert recommendation["recommended_quantity"] == 27
    assert recommendation["recommended_box_quantity"] == 3
    for field in ("quantity", "box_quantity"):  # 명시적 null은 생략과 다르며 초안을 만들지 않는다
        invalid = {"items": [{"product_id": product.id, field: None}]}
        assert client.post(f"{RECOMMENDATIONS}/drafts", json=invalid).status_code == 422
    response = client.post(f"{RECOMMENDATIONS}/drafts", json={"items": [{"product_id": product.id}]})
    assert response.status_code == 201, response.json()
    [order] = response.json()["data"]
    [line] = order["items"]
    assert (line["recommended_quantity"], line["box_quantity"], line["quantity"]) == (27, 3, 30)
    assert line["line_total"] == 30_015

    # 품목 설정 변경 뒤 초안을 고쳐도 기존 줄의 당시 입수와 단가를 쓴다.
    response = client.patch(f"{PRODUCTS}/{product.id}", json={"units_per_box": 12, "box_unit_cost": 12_000})
    assert response.status_code == 200
    url = f"{ORDERS}/{order['id']}"
    response = client.patch(url, json={"items": [{"product_id": product.id, "box_quantity": 3}]})
    assert response.status_code == 200, response.json()
    [saved] = response.json()["data"]["items"]
    assert (saved["units_per_box"], saved["box_unit_price"], saved["line_total"]) == (10, 10_005, 30_015)
    assert client.post(f"{url}/approve").status_code == 200
    assert client.post(f"{url}/order").status_code == 200

    receipt = {"purchase_order_item_id": line["id"], "box_quantity": 2}
    response = client.post(f"{url}/receipts", json={"items": [receipt]})
    assert response.status_code == 201, response.json()
    order = response.json()["data"]
    assert order["status"] == "ORDERED" and order["items"][0]["received_quantity"] == 20
    movement = session.scalar(select(InventoryMovement).where(InventoryMovement.purchase_order_item_id == line["id"]))
    assert movement.movement_type == "RECEIPT" and movement.quantity == 20
    response = client.post(f"{url}/receipts", json={"items": [receipt]})
    assert response.status_code == 409 and response.json()["error"]["code"] == "OVER_RECEIPT"
    assert response.json()["error"]["details"]["remaining"] == 10

    response = client.post(f"/api/v1/inventory-movements/{movement.id}/corrections", json={"quantity": 3, "reason": "오입력"})
    assert response.status_code == 201
    assert client.get(url).json()["data"]["items"][0]["received_quantity"] == 17
    response = client.post(f"{url}/receipts", json={"items": [{"purchase_order_item_id": line["id"], "quantity": 13}]})
    assert response.status_code == 201 and response.json()["data"]["status"] == "RECEIVED"


def test_manual_box_order_validation_and_legacy_lines(client, session, world):
    plain = add_product(session, world, "PLAIN")
    foreign = add_product(session, world, "FOREIGN-BOX", key="b", units_per_box=10, box_unit_cost=500)
    session.commit()
    login_as(client)
    supplier_id = world["a_supplier"].id
    product = {"sku": "BOX", "name": "박스 품목", "unit": "개", "unit_cost": 1000,
               "default_supplier_id": supplier_id, "units_per_box": 10}
    assert client.post(PRODUCTS, json=product).status_code == 422
    response = client.post(PRODUCTS, json={**product, "box_unit_cost": 10_005})
    assert response.status_code == 201, response.json()
    product_id = response.json()["data"]["id"]
    assert client.patch(f"{PRODUCTS}/{product_id}", json={"units_per_box": None}).status_code == 422

    for pid, boxes, status in [(foreign.id, 1, 404), (plain.id, 1, 422), (product_id, 100_001, 422)]:
        body = {"supplier_id": supplier_id, "items": [{"product_id": pid, "box_quantity": boxes}]}
        assert client.post(ORDERS, json=body).status_code == status
    body = {"supplier_id": supplier_id, "items": [
        {"product_id": product_id, "box_quantity": 3},
        {"product_id": plain.id, "quantity": 2, "unit_price": 1000},
    ]}
    response = client.post(ORDERS, json=body)
    assert response.status_code == 201, response.json()
    order = response.json()["data"]
    box, legacy = order["items"]
    assert (box["quantity"], box["line_total"], legacy["quantity"], legacy["line_total"]) == (30, 30_015, 2, 2000)
    assert legacy["units_per_box"] is None

    # 품목 설정을 해제한 뒤 기존 화면이 재고 단위로 PATCH해도 박스 조건을 보존한다.
    assert client.patch(f"{PRODUCTS}/{product_id}", json={"units_per_box": None, "box_unit_cost": None}).status_code == 200
    response = client.patch(f"{ORDERS}/{order['id']}", json={"items": [
        {field: row[field] for field in ("product_id", "quantity", "unit_price")} for row in order["items"]
    ]})
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["items"][0]["line_total"] == 30_015
