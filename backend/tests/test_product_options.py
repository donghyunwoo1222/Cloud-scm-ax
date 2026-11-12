"""품목 옵션 칸(color·size·spec·group_code, #178) 테스트. 준비 데이터 world(회사 A·B)는 conftest."""

import pytest  # 테스트 도구

from app.models import Product  # 품목 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/products"  # 품목 경로


def new_product(world, **override) -> dict:
    """품목 등록 요청 본문 (기본 공급업체: A업체)."""
    body = {"sku": "TS-BK-M", "name": "기본 티셔츠", "unit": "개", "unit_cost": 5000,
            "default_supplier_id": world["a_supplier"].id}
    return {**body, **override}


def add(session, world, key, sku, **fields) -> Product:
    """DB 에 품목 하나 (회사 key: a/b)."""
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=f"품목{sku}", unit="개", unit_cost=1000,
                default_supplier_id=world[f"{key}_supplier"].id, **fields)
    session.add(p)
    session.commit()
    return p


# ----- 저장·수정 -----
def test_create_saves_options_and_group_code_upper(client, world):
    login_as(client)
    r = client.post(URL, json=new_product(world, color=" 검정 ", size="M", spec="2L", group_code="ts-basic"))
    assert r.status_code == 201, r.json()
    d = r.json()["data"]
    assert (d["color"], d["size"], d["spec"], d["group_code"]) == ("검정", "M", "2L", "TS-BASIC")  # 공백 제거, 그룹 코드는 대문자
    assert client.get(f"{URL}/{d['id']}").json()["data"]["group_code"] == "TS-BASIC"  # 조회에도 그대로


def test_update_and_clear_options(client, world):
    login_as(client)
    pid = client.post(URL, json=new_product(world, color="검정", group_code="A1")).json()["data"]["id"]
    d = client.patch(f"{URL}/{pid}", json={"size": " L ", "group_code": "b2"}).json()["data"]
    assert (d["color"], d["size"], d["group_code"]) == ("검정", "L", "B2")  # 보낸 칸만 바뀐다
    d = client.patch(f"{URL}/{pid}", json={"color": None}).json()["data"]
    assert d["color"] is None and d["size"] == "L"  # null 이면 비운다


def test_blank_option_becomes_null(client, world):
    login_as(client)
    d = client.post(URL, json=new_product(world, color="   ", group_code="")).json()["data"]
    assert d["color"] is None and d["group_code"] is None  # 빈 글자는 값으로 저장하지 않는다


@pytest.mark.parametrize("field", ["color", "size", "spec", "group_code"])
def test_option_over_50_chars_is_422(client, world, field):
    login_as(client)
    assert client.post(URL, json=new_product(world, **{field: "가" * 51})).status_code == 422
    assert client.post(URL, json=new_product(world, **{field: "가" * 50})).status_code == 201  # 50자는 된다


def test_product_without_options_returns_null(client, world, session):
    p = add(session, world, "a", "OLD-1")  # 옵션 칸을 모르던 기존 품목과 같은 모양
    login_as(client)
    d = client.get(f"{URL}/{p.id}").json()["data"]
    assert (d["color"], d["size"], d["spec"], d["group_code"]) == (None, None, None, None)


# ----- 검색·필터 -----
@pytest.fixture
def options_data(world, session):
    a = add(session, world, "a", "TS-BK-M", color="검정", size="M", group_code="TS-BASIC")
    b = add(session, world, "a", "TS-WH-L", color="흰색", size="L", group_code="TS-BASIC")
    c = add(session, world, "a", "DT-2L", spec="2L", group_code="DETERGENT")
    add(session, world, "b", "B-BK", color="검정", group_code="TS-BASIC")  # 다른 회사: 같은 옵션이어도 안 보여야 한다
    return a, b, c


@pytest.mark.parametrize("q,expected", [
    ("검정", {"TS-BK-M"}), ("흰", {"TS-WH-L"}), ("2l", {"DT-2L"}),  # 옵션 값(대소문자 무시)
    ("ts-basic", {"TS-BK-M", "TS-WH-L"}), ("detergent", {"DT-2L"}),  # 그룹 코드
    ("%", set()),  # %는 글자 그대로 읽는다
])
def test_q_matches_options_for_products_and_stock(client, options_data, q, expected):
    login_as(client)
    for path in (URL, "/api/v1/stock"):  # 두 목록이 같은 검색 함수를 쓴다
        rows = client.get(path, params={"q": q}).json()["data"]
        assert {r["sku"] for r in rows} == expected, path


def test_group_code_filter_exact(client, options_data):
    login_as(client)
    for path in (URL, "/api/v1/stock"):
        rows = client.get(path, params={"group_code": "ts-basic"}).json()["data"]  # 소문자로 보내도 같다
        assert {r["sku"] for r in rows} == {"TS-BK-M", "TS-WH-L"}  # 다른 회사의 TS-BASIC 은 없다
        assert client.get(path, params={"group_code": "TS"}).json()["data"] == []  # 부분 일치가 아니다
        rows = client.get(path, params={"group_code": "TS-BASIC", "q": "검정"}).json()["data"]
        assert {r["sku"] for r in rows} == {"TS-BK-M"}  # 검색어와 함께 쓰면 둘 다 만족


def test_stock_with_status_filter_also_uses_group_code(client, options_data):
    login_as(client)
    rows = client.get("/api/v1/stock", params={"group_code": "DETERGENT", "status": "UNKNOWN"}).json()["data"]
    assert {r["sku"] for r in rows} == {"DT-2L"}  # 상태 필터 경로(calculate_for)도 그룹 코드를 지킨다


# ----- 다른 회사 격리 -----
def test_other_company_options_not_visible(client, world, session):
    b = add(session, world, "b", "B-1", color="빨강", group_code="B-GRP")
    login_as(client)  # 회사 A 담당자
    assert client.get(f"{URL}/{b.id}").status_code == 404
    assert client.patch(f"{URL}/{b.id}", json={"color": "파랑"}).status_code == 404
    assert client.get(URL, params={"q": "빨강"}).json()["data"] == []
    assert client.get(URL, params={"group_code": "B-GRP"}).json()["data"] == []


# ----- 품목을 보여주는 다른 응답에도 옵션이 내려간다 -----
def test_options_in_stock_recommendation_movement_and_po_item(client, world, session):
    p = add(session, world, "a", "OPT-1", color="검정", size="M", spec="30롤", group_code="OPT")
    login_as(client)
    s = next(r for r in client.get("/api/v1/stock").json()["data"] if r["sku"] == "OPT-1")
    assert (s["color"], s["size"], s["spec"], s["group_code"]) == ("검정", "M", "30롤", "OPT")

    reco = client.get("/api/v1/recommendations").json()["data"]  # 이력이 없으면 제외 목록에 나온다
    ex = next(r for r in reco["excluded"] if r["product_sku"] == "OPT-1")
    assert (ex["color"], ex["size"], ex["spec"], ex["group_code"]) == ("검정", "M", "30롤", "OPT")

    assert client.post("/api/v1/inventory-movements", json={
        "product_id": p.id, "movement_type": "RECEIPT", "quantity": 5}).status_code == 201
    m = client.get("/api/v1/inventory-movements").json()["data"][0]
    assert (m["product_color"], m["product_size"], m["product_spec"], m["product_group_code"]) == ("검정", "M", "30롤", "OPT")

    po = client.post("/api/v1/purchase-orders", json={
        "supplier_id": world["a_supplier"].id, "items": [{"product_id": p.id, "quantity": 3, "unit_price": 800}]})
    assert po.status_code == 201, po.json()
    item = po.json()["data"]["items"][0]
    assert (item["color"], item["size"], item["spec"], item["group_code"]) == ("검정", "M", "30롤", "OPT")
