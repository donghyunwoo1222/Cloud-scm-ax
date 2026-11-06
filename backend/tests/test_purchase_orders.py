"""발주서 작성·수정·조회 API (#33) 테스트. 준비 데이터 world 는 conftest. 승인·입고는 #34·#35. 동시 작성은 test_concurrency.py."""

import pytest  # 테스트 도구
from sqlalchemy import select  # SELECT 문

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/purchase-orders"  # 발주 경로


def add_product(session, world, key, sku, **fields):
    """품목 하나 (회사 key: a/b)."""
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=f"품목{sku}", unit="개", unit_cost=1000,
                default_supplier_id=world[f"{key}_supplier"].id, **fields)
    session.add(p)
    session.flush()
    return p


@pytest.fixture
def data(world, session):
    """A: 활성 품목 p1·p2, 비활성 p3, 비활성 업체 sx. B: 품목 b1."""
    sx = Supplier(company_id=world["a_company"].id, name="비활성업체", lead_time_days=3, is_active=False)
    session.add(sx)
    out = {"p1": add_product(session, world, "a", "P1"), "p2": add_product(session, world, "a", "P2"),
           "p3": add_product(session, world, "a", "P3", is_active=False), "b1": add_product(session, world, "b", "B1"), "sx": sx}
    session.commit()
    return out


def line(product, quantity=1, price=800):
    """요청의 품목 줄 하나."""
    return {"product_id": product.id, "quantity": quantity, "unit_price": price}


def body(world, *items, **fields):
    """작성 요청 본문 (회사 A 공급업체). items 는 품목 줄."""
    return {"supplier_id": world["a_supplier"].id, "items": list(items), **fields}


def new_supplier(client, name):
    """공급업체를 API 로 하나 더 등록 → id."""
    return client.post("/api/v1/suppliers", json={"name": name, "lead_time_days": 1}).json()["data"]["id"]


# ----- 완료 기준 1: 발주번호 자동 부여 -----
def test_create_assigns_po_number_and_draft(client, world, data):
    login_as(client)
    r = client.post(URL, json=body(world, line(data["p1"], 10), line(data["p2"], 5), due_date="2026-11-20", memo="급함"))
    assert r.status_code == 201, r.json()
    d = r.json()["data"]
    assert d["po_number"] == f"PO-{seoul_today():%Y%m%d}-001" and d["status"] == "DRAFT"
    assert d["supplier_name"] == "A업체" and d["due_date"] == "2026-11-20" and d["created_by"] == world["a_staff"].id
    assert [(i["product_sku"], i["quantity"], i["unit_price"], i["received_quantity"]) for i in d["items"]] == [("P1", 10, 800, 0), ("P2", 5, 800, 0)]
    second = client.post(URL, json={"supplier_id": new_supplier(client, "둘째업체"), "items": [line(data["p1"])]})  # 다른 업체면 같은 날 두 번째 번호
    assert second.json()["data"]["po_number"].endswith("-002")


def test_create_validation(client, world, data):
    login_as(client)
    assert client.post(URL, json=body(world)).status_code == 422  # 줄 0개
    assert client.post(URL, json=body(world, line(data["p1"], 0))).status_code == 422  # 수량 1 미만
    assert client.post(URL, json=body(world, line(data["p1"], 1.0))).status_code == 422  # 엄격한 정수
    assert client.post(URL, json=body(world, line(data["p1"]), status="APPROVED")).status_code == 422  # 상태는 못 정한다


# ----- 완료 기준 3: 같은 품목 두 번 → DUPLICATE_ITEM -----
def test_duplicate_item(client, world, data):
    login_as(client)
    r = client.post(URL, json=body(world, line(data["p1"]), line(data["p1"], 2)))
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ITEM"
    ok = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    r = client.patch(f"{URL}/{ok['id']}", json={"items": [line(data["p1"]), line(data["p1"])]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_ITEM"


# ----- 공급업체당 DRAFT 1장 -----
def test_one_draft_per_supplier(client, world, data):
    login_as(client)
    first = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    r = client.post(URL, json=body(world, line(data["p2"])))
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "DUPLICATE_DRAFT"
    assert first["po_number"] in err["message"] and err["details"]["purchase_order_id"] == first["id"]


# ----- 완료 기준 4: 비활성 공급업체·품목 제외 -----
def test_inactive_supplier_and_product_rejected(client, world, data):
    login_as(client)
    r = client.post(URL, json={**body(world, line(data["p1"])), "supplier_id": data["sx"].id})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INACTIVE_REFERENCE"
    r = client.post(URL, json=body(world, line(data["p3"])))
    assert r.status_code == 409 and r.json()["error"]["code"] == "INACTIVE_REFERENCE"
    ok = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    r = client.patch(f"{URL}/{ok['id']}", json={"items": [line(data["p3"])]})  # 새 줄이 비활성
    assert r.status_code == 409 and r.json()["error"]["code"] == "INACTIVE_REFERENCE"


def test_existing_line_may_stay_after_product_inactive(client, world, data, session):
    """이미 든 품목이 나중에 비활성이 되어도 DRAFT 수정은 된다 (승인 때 막는다, #34)."""
    login_as(client)
    ok = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    data["p1"].is_active = False
    session.commit()
    r = client.patch(f"{URL}/{ok['id']}", json={"items": [line(data["p1"], 9, 5)]})
    assert r.status_code == 200 and r.json()["data"]["items"][0]["quantity"] == 9


# ----- 완료 기준 2: DRAFT 일 때만 수정 -----
def test_patch_draft_replaces_items(client, world, data):
    login_as(client)
    ok = client.post(URL, json=body(world, line(data["p1"], 10), memo="처음")).json()["data"]
    first_item = ok["items"][0]["id"]
    r = client.patch(f"{URL}/{ok['id']}", json={"memo": None, "due_date": "2026-12-01", "items": [line(data["p1"], 20, 700), line(data["p2"], 3, 100)]})
    d = r.json()["data"]
    assert r.status_code == 200 and d["memo"] is None and d["due_date"] == "2026-12-01"
    assert [(i["product_sku"], i["quantity"], i["unit_price"]) for i in d["items"]] == [("P1", 20, 700), ("P2", 3, 100)]
    assert d["items"][0]["id"] == first_item  # 있던 줄은 같은 줄을 고친다
    d = client.patch(f"{URL}/{ok['id']}", json={"items": [line(data["p2"], 3, 100)]}).json()["data"]
    assert [i["product_sku"] for i in d["items"]] == ["P2"]  # 빠진 줄은 삭제
    assert client.patch(f"{URL}/{ok['id']}", json={"items": None}).status_code == 422
    assert client.patch(f"{URL}/{ok['id']}", json={"supplier_id": 1}).status_code == 422  # 업체 변경 불가


def test_patch_non_draft_rejected(client, world, data, session):
    login_as(client)
    ok = client.post(URL, json=body(world, line(data["p1"], 10))).json()["data"]
    session.get(PurchaseOrder, ok["id"]).status = "APPROVED"
    session.commit()
    r = client.patch(f"{URL}/{ok['id']}", json={"memo": "수정"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATUS"
    assert client.get(f"{URL}/{ok['id']}").json()["data"]["memo"] is None  # 안 바뀜


def test_failed_patch_changes_nothing(client, world, data):
    """줄 검사에 실패하면 납기·메모도 바뀌지 않는다."""
    login_as(client)
    ok = client.post(URL, json=body(world, line(data["p1"]), memo="원본")).json()["data"]
    r = client.patch(f"{URL}/{ok['id']}", json={"memo": "바뀜", "items": [line(data["p3"])]})
    assert r.status_code == 409
    assert client.get(f"{URL}/{ok['id']}").json()["data"]["memo"] == "원본"


# ----- 조회: 공급업체별, 누적 입고량, 페이지 -----
def test_list_by_supplier_with_received_quantity(client, world, data, session):
    login_as(client)
    ok = client.post(URL, json=body(world, line(data["p1"], 100))).json()["data"]
    item = session.get(PurchaseOrderItem, ok["items"][0]["id"])

    def move(mtype, direction, qty, **extra):
        """발주 줄에 연결된 이력 (입고 API 는 #35 라 이력을 직접 넣는다)."""
        session.add(InventoryMovement(company_id=item.company_id, product_id=item.product_id, created_by=world["a_staff"].id, movement_type=mtype,
                                      direction=direction, quantity=qty, movement_date=seoul_today(), purchase_order_item_id=item.id, **extra))
        session.flush()

    move("RECEIPT", "IN", 60)
    move("RECEIPT", "IN", 10)
    first = session.scalar(select(InventoryMovement).where(InventoryMovement.purchase_order_item_id == item.id).order_by(InventoryMovement.id))
    move("CORRECTION", "OUT", 5, reason="오입력", reverses_movement_id=first.id)
    session.commit()
    rows = client.get(URL, params={"supplier_id": world["a_supplier"].id}).json()
    assert rows["meta"] == {"page": 1, "page_size": 20, "total": 1}
    assert rows["data"][0]["items"][0]["received_quantity"] == 65 and rows["data"][0]["received_at"] is None  # 60 + 10 − 5
    assert client.get(URL, params={"supplier_id": world["b_supplier"].id}).json()["meta"]["total"] == 0  # 다른 회사 업체 id 는 빈 목록
    for size in (0, 101):
        assert client.get(URL, params={"page_size": size}).status_code == 422


def test_list_latest_first(client, world, data):
    login_as(client)
    a = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    b = client.post(URL, json={"supplier_id": new_supplier(client, "셋째업체"), "items": [line(data["p1"])]}).json()["data"]
    assert [o["id"] for o in client.get(URL).json()["data"]] == [b["id"], a["id"]]


def test_list_filter_by_status(client, world, data):
    login_as(client)
    a = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]  # DRAFT
    b = client.post(URL, json={"supplier_id": new_supplier(client, "넷째업체"), "items": [line(data["p1"])]}).json()["data"]
    login_as(client, "admin@a.test")
    assert client.post(f"{URL}/{b['id']}/approve").status_code == 200  # b 만 APPROVED
    ids = lambda status: [o["id"] for o in client.get(URL, params={"status": status}).json()["data"]]  # 상태별 목록의 id
    assert ids("DRAFT") == [a["id"]] and ids("APPROVED") == [b["id"]] and ids("ORDERED") == []  # 상태가 맞는 것만
    assert client.get(URL, params={"status": "BOGUS"}).status_code == 422  # 모르는 상태는 422


# ----- 회사 분리 -----
def test_company_isolation(client, world, data):
    login_as(client)
    mine = client.post(URL, json=body(world, line(data["p1"]))).json()["data"]
    assert client.post(URL, json={"supplier_id": world["b_supplier"].id, "items": [line(data["p1"])]}).status_code == 404  # 다른 회사 공급업체
    assert client.post(URL, json=body(world, line(data["b1"]))).status_code == 404  # 다른 회사 품목
    login_as(client, "staff@b.test")
    assert client.get(URL).json()["meta"]["total"] == 0  # 회사 A 발주는 안 보인다
    assert client.get(f"{URL}/{mine['id']}").status_code == 404
    assert client.patch(f"{URL}/{mine['id']}", json={"memo": "x"}).status_code == 404


def test_requires_login(client, world, data):
    assert client.get(URL).status_code == 401
    assert client.post(URL, json={}).status_code == 401


# ----- 품목 단위 unit (#93) -----
OLD_FIELDS = {"id", "product_id", "product_sku", "product_name", "quantity", "unit_price", "recommended_quantity", "recommendation_reason", "received_quantity"}  # unit 추가 전부터 있던 칸


def test_item_unit_in_create_patch_get_and_old_fields_kept(client, world, data, session):
    """생성·수정·상세·목록 응답 모두 품목 단위를 담고, 기존 칸은 그대로다."""
    data["p2"].unit = "박스"  # 단위가 다른 품목
    session.commit()
    login_as(client)
    created = client.post(URL, json=body(world, line(data["p1"], 10), line(data["p2"], 5))).json()["data"]
    units = lambda d: {i["product_sku"]: i["unit"] for i in d["items"]}  # SKU → 단위
    assert units(created) == {"P1": "개", "P2": "박스"}
    patched = client.patch(f"{URL}/{created['id']}", json={"items": [line(data["p2"], 7)]}).json()["data"]
    assert units(patched) == {"P2": "박스"}
    assert units(client.get(f"{URL}/{created['id']}").json()["data"]) == {"P2": "박스"}
    assert units(client.get(URL).json()["data"][0]) == {"P2": "박스"}
    item = patched["items"][0]
    assert set(item) == OLD_FIELDS | {"unit", "units_per_box", "box_unit_price", "box_quantity", "line_total"}
    assert item["box_quantity"] is None and item["line_total"] == item["quantity"] * item["unit_price"]
    assert (item["quantity"], item["unit_price"], item["received_quantity"], item["recommended_quantity"]) == (7, 800, 0, None)  # 값도 그대로


def test_item_unit_comes_from_own_company_product(client, world, data, session):
    """다른 회사 품목의 단위가 섞이지 않는다 (같은 SKU 라도 자기 회사 품목 값)."""
    mine = add_product(session, world, "a", "SAME")
    mine.unit = "개"
    other = add_product(session, world, "b", "SAME")
    other.unit = "롤"  # 다른 회사의 같은 SKU
    session.commit()
    login_as(client)
    d = client.post(URL, json=body(world, line(mine, 1))).json()["data"]
    assert d["items"][0]["unit"] == "개"
    login_as(client, "staff@b.test")
    assert client.get(f"{URL}/{d['id']}").status_code == 404  # 다른 회사는 발주서 자체를 못 본다


def test_query_count_same_for_3_and_30_items(client, world, data, session, engine):
    """발주 줄 3개와 30개의 쿼리 횟수가 같다 (줄마다 단위를 따로 묻지 않는다, N+1 없음)."""
    from sqlalchemy import event  # SQL 실행 감시 도구

    def count_queries(n):
        products = [add_product(session, world, "a", f"U{n}-{k}") for k in range(n)]  # 품목 n개
        session.commit()
        login_as(client)
        po = client.post(URL, json=body(world, *[line(p, 1) for p in products])).json()["data"]
        seen = []  # 실행된 SQL
        listener = lambda *args: seen.append(args[2])  # before_cursor_execute 의 SQL 문장
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert client.get(f"{URL}/{po['id']}").status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        client.post(f"{URL}/{po['id']}/cancel")  # 같은 공급업체의 DRAFT 는 1장뿐이라 정리한다
        return len(seen)

    assert count_queries(3) == count_queries(30)
