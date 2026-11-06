"""품목 API (#26) 테스트. 준비 데이터 world(회사 A·B, 관리자·담당자, A업체·B업체)는 conftest."""

import pytest  # 테스트 도구

from app.models import Product, Supplier  # 품목, 공급업체 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/products"  # 품목 경로


def new_product(world, **override) -> dict:
    """품목 등록 요청 본문 (기본 공급업체: A업체)."""
    body = {"sku": "TS-BK-M", "name": "기본 티셔츠", "unit": "개", "unit_cost": 5000,
            "default_supplier_id": world["a_supplier"].id}
    return {**body, **override}


@pytest.fixture
def b_product(world, session):
    """회사 B 의 품목 하나 (회사 분리 확인용)."""
    product = Product(company_id=world["b_company"].id, sku="B-001", name="B품목", unit="개",
                      unit_cost=100, default_supplier_id=world["b_supplier"].id)
    session.add(product)
    session.commit()  # 확정 (테스트 끝에 함께 되돌림)
    return product


def test_search_finds_product_after_first_hundred(client, world, session):
    company_id = world["a_company"].id
    session.add_all([Product(company_id=company_id, **new_product(world, sku=f"SKU-{i:03}")) for i in range(101)])
    session.commit()
    login_as(client)
    first_page = client.get(URL, params={"page_size": 100}).json()["data"]
    assert len(first_page) == 100 and all(p["sku"] != "SKU-000" for p in first_page)
    result = client.get(URL, params={"q": "sku-000"}).json()
    assert result["meta"]["total"] == 1
    assert result["data"][0]["sku"] == "SKU-000"


# ----- 완료 기준 1: 등록·수정·비활성이 된다 (관리자·담당자 모두) -----
@pytest.mark.parametrize("email", ["staff@a.test", "admin@a.test"], ids=["staff", "admin"])
def test_create_update_deactivate(client, world, email):
    """등록 201(기본 공급업체 요약 포함, 재고 숫자 없음) → 수정 → 비활성 → 다시 활성."""
    login_as(client, email)
    created = client.post(URL, json=new_product(world))
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["safety_stock"] == 0  # 안전재고 기본 0
    assert data["default_supplier"] == {"id": world["a_supplier"].id, "name": "A업체", "lead_time_days": 5}
    assert not {"stock", "current_stock", "quantity"} & data.keys()  # 재고 숫자는 없다 (#31)
    pid = data["id"]

    updated = client.patch(f"{URL}/{pid}", json={"unit_cost": 5500, "safety_stock": 20})
    assert updated.json()["data"]["unit_cost"] == 5500
    assert updated.json()["data"]["name"] == "기본 티셔츠"  # 보내지 않은 칸은 그대로
    assert client.patch(f"{URL}/{pid}", json={"is_active": False}).json()["data"]["is_active"] is False
    assert client.get(f"{URL}/{pid}").json()["data"]["is_active"] is False  # 상세는 비활성도 보인다
    assert client.patch(f"{URL}/{pid}", json={"is_active": True}).json()["data"]["is_active"] is True


def test_no_delete_route(client, world, b_product):
    """삭제 경로는 없다 (405)."""
    login_as(client)
    assert client.delete(f"{URL}/1").status_code == 405


# ----- 완료 기준 2: SKU 중복이 막힌다 -----
def test_sku_normalized_and_duplicate(client, world, b_product):
    """SKU 는 공백 제거·대문자로 저장, 대소문자만 달라도 409 DUPLICATE_SKU. 다른 회사의 같은 SKU 는 허용."""
    login_as(client)
    first = client.post(URL, json=new_product(world, sku="  ts-bk-m "))
    assert first.json()["data"]["sku"] == "TS-BK-M"  # 정리되어 저장
    dup = client.post(URL, json=new_product(world, sku="Ts-Bk-M"))  # 같은 SKU
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_SKU"
    other = client.post(URL, json=new_product(world, sku="TS-WH-L")).json()["data"]
    rename = client.patch(f"{URL}/{other['id']}", json={"sku": "ts-bk-m"})  # 수정으로 겹치게 만들기
    assert rename.json()["error"]["code"] == "DUPLICATE_SKU"
    assert client.post(URL, json=new_product(world, sku="b-001")).status_code == 201  # 회사 B 에 있는 SKU 지만 A 에선 허용


# ----- 완료 기준 3: S8 회사 X 로 로그인하면 회사 Y 품목은 목록에 없고 상세는 404 -----
def test_s8_other_company_product(client, world, b_product):
    """A 로그인: B 품목은 목록에 없고, 상세는 없는 id 와 같은 404, 수정도 404."""
    login_as(client)
    client.post(URL, json=new_product(world))  # A 품목 하나
    skus = [p["sku"] for p in client.get(URL, params={"include_inactive": "true"}).json()["data"]]
    assert skus == ["TS-BK-M"]  # B-001 이 없다
    other = client.get(f"{URL}/{b_product.id}")
    missing = client.get(f"{URL}/999999")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()  # 있는지조차 알 수 없다
    assert client.patch(f"{URL}/{b_product.id}", json={"is_active": False}).status_code == 404  # PATCH 도 404


# ----- 기본 공급업체: 같은 회사의 활성 업체만 -----
def test_default_supplier_other_company_is_404(client, world):
    """등록·수정 모두: 본문의 default_supplier_id 가 B 회사 업체면 404 + details 에 칸 이름."""
    login_as(client)
    created = client.post(URL, json=new_product(world, default_supplier_id=world["b_supplier"].id))
    assert created.status_code == 404
    assert created.json()["error"]["details"] == [{"field": "default_supplier_id", "reason": "not_found"}]
    pid = client.post(URL, json=new_product(world)).json()["data"]["id"]
    updated = client.patch(f"{URL}/{pid}", json={"default_supplier_id": world["b_supplier"].id})
    assert updated.status_code == 404
    assert updated.json()["error"]["details"][0]["field"] == "default_supplier_id"


def test_default_supplier_inactive_is_409(client, world, session):
    """비활성 업체를 고르면 등록·수정 모두 409 INACTIVE_REFERENCE. 이미 연결된 품목의 다른 칸 수정은 된다."""
    login_as(client)
    pid = client.post(URL, json=new_product(world)).json()["data"]["id"]  # A업체로 등록
    inactive = Supplier(company_id=world["a_company"].id, name="쉬는업체", lead_time_days=1, is_active=False)
    session.add(inactive)
    session.commit()
    created = client.post(URL, json=new_product(world, sku="X-1", default_supplier_id=inactive.id))
    assert created.status_code == 409
    assert created.json()["error"]["code"] == "INACTIVE_REFERENCE"
    assert client.patch(f"{URL}/{pid}", json={"default_supplier_id": inactive.id}).status_code == 409

    client.patch(f"/api/v1/suppliers/{world['a_supplier'].id}", json={"is_active": False})  # 연결된 A업체를 비활성으로
    renamed = client.patch(f"{URL}/{pid}", json={"name": "새 이름"})  # 공급업체를 바꾸지 않는 수정
    assert renamed.status_code == 200  # 허용 (기존 연결은 그대로 둔다)


# ----- 단가·안전재고: 0 이상 정수 -----
@pytest.mark.parametrize("field", ["unit_cost", "safety_stock"])
@pytest.mark.parametrize("value", [-1, 3.5, 3.0, "3", True], ids=["negative", "decimal", "float", "string", "bool"])
def test_non_negative_integers(client, world, field, value):
    """단가·안전재고는 음수·소수·문자·참거짓이면 422, details 에 칸 이름."""
    login_as(client)
    response = client.post(URL, json=new_product(world, **{field: value}))
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == field


def test_patch_null_rules(client, world):
    """PATCH: 필수 칸을 null 로 비우면 422, 0 은 허용."""
    login_as(client)
    pid = client.post(URL, json=new_product(world)).json()["data"]["id"]
    assert client.patch(f"{URL}/{pid}", json={"default_supplier_id": None}).status_code == 422
    assert client.patch(f"{URL}/{pid}", json={"unit_cost": None}).status_code == 422
    assert client.patch(f"{URL}/{pid}", json={"unit_cost": 0}).json()["data"]["unit_cost"] == 0


# ----- 목록: 최신순·쪽 나누기·비활성 필터·검색 -----
def test_list_paging_filter_search(client, world, b_product):
    """최신순, meta, 비활성 기본 숨김, q 는 SKU·품목명 부분 일치(대소문자 무시, % 는 글자 그대로)."""
    login_as(client)
    for sku, name in (("TS-BK-M", "기본 티셔츠"), ("CAP-01", "Summer 모자"), ("PCT-50", "50% 세일 양말")):
        client.post(URL, json=new_product(world, sku=sku, name=name))
    first_id = client.get(URL).json()["data"][-1]["id"]  # 가장 먼저 만든 품목 (티셔츠)
    client.patch(f"{URL}/{first_id}", json={"is_active": False})  # 티셔츠 비활성 → 활성 2개

    body = client.get(URL).json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 2}  # 비활성 제외, B 품목 제외
    assert body["data"][0]["sku"] == "PCT-50"  # 가장 최근 등록이 먼저
    assert client.get(URL, params={"include_inactive": "true"}).json()["meta"]["total"] == 3
    assert len(client.get(URL, params={"page": 2, "page_size": 1}).json()["data"]) == 1

    def search(q):
        return [p["sku"] for p in client.get(URL, params={"q": q, "include_inactive": "true"}).json()["data"]]

    assert search("cap") == ["CAP-01"]  # SKU 부분 일치, 대소문자 무시
    assert search("SUMMER") == ["CAP-01"]  # 품목명 부분 일치, 대소문자 무시
    assert search("%") == ["PCT-50"]  # % 가 "아무 글자"로 해석되지 않는다
    assert search("B-001") == []  # 다른 회사 품목은 검색에도 없다


def test_list_default_supplier_before_paging(client, world, session, b_product):
    """선택한 업체와 검색·활성 조건을 적용한 뒤 쪽을 나누고 다른 회사 품목은 제외한다."""
    company_id = world["a_company"].id  # 로그인할 회사의 번호
    supplier = Supplier(company_id=company_id, name="비활성 업체", lead_time_days=2, is_active=False)  # 과거에 연결된 업체
    session.add(supplier)  # 업체를 테스트 트랜잭션에 추가한다
    session.flush()  # 업체 번호를 만든다
    session.add_all([  # 선택 업체 2개를 먼저, 다른 업체 1개를 최신으로 넣는다
        Product(company_id=company_id, sku="FILTER-A", name="필터 품목", unit="개", unit_cost=100, default_supplier_id=supplier.id),
        Product(company_id=company_id, sku="FILTER-B", name="필터 품목", unit="개", unit_cost=100, default_supplier_id=supplier.id, is_active=False),
        Product(company_id=company_id, sku="FILTER-C", name="필터 품목", unit="개", unit_cost=100, default_supplier_id=world["a_supplier"].id),
    ])
    session.commit()  # 테스트 끝에 되돌리는 세이브포인트까지만 확정한다
    login_as(client)  # A 회사로 로그인한다
    params = {"default_supplier_id": supplier.id, "page_size": 1, "q": "필터"}  # 활성 품목만 기본값으로 조회한다
    first = client.get(URL, params=params).json()  # 비활성 업체에 연결된 활성 품목은 나온다
    assert [p["sku"] for p in first["data"]] == ["FILTER-A"]  # 최신의 다른 업체 품목은 쪽을 나누기 전에 빠진다
    assert first["meta"] == {"page": 1, "page_size": 1, "total": 1}  # 개수도 같은 조건을 쓴다

    second = client.get(URL, params={**params, "page": 2, "include_inactive": True}).json()  # 비활성 포함으로 둘째 쪽을 읽는다
    assert [p["sku"] for p in second["data"]] == ["FILTER-A"]  # 첫째 쪽은 더 최근에 추가한 비활성 품목이다
    assert second["meta"]["total"] == 2  # 같은 업체의 활성·비활성 품목만 센다
    searched = client.get(URL, params={**params, "q": "FILTER-B", "include_inactive": True}).json()  # 검색어도 함께 적용한다
    assert [p["sku"] for p in searched["data"]] == ["FILTER-B"]  # SKU와 업체가 모두 일치한다
    foreign = client.get(URL, params={"default_supplier_id": world["b_supplier"].id}).json()  # B 회사 공급업체 번호를 보낸다
    assert foreign["data"] == [] and foreign["meta"]["total"] == 0  # 다른 회사 품목의 행과 개수 모두 감춘다


# ----- 로그인 -----
def test_anonymous_is_401(client, world):
    """로그인 안 함 → 401."""
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=new_product(world)).status_code == 401
