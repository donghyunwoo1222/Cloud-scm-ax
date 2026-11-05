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


# ----- 이력: 유형 여러 개·등록순 정렬 (#90) -----
def ids(response):
    """응답 줄들의 번호 목록 (순서 확인용)."""
    return [m["id"] for m in response.json()["data"]]


def test_movements_multiple_types(client, world, data, session):
    """movement_type 을 여러 번 보내면 그중 하나인 이력이 모두 나온다. 예전처럼 마지막 값만 적용되면 안 된다."""
    add_move(session, world, "a", data["p1"], "DISPOSAL", "OUT", 1)
    session.commit()
    login_as(client)
    got = client.get(MOVES, params={"movement_type": ["SALE", "ADJUSTMENT"]}).json()
    assert got["meta"]["total"] == 3  # 판매 1 + 조정 2 (마지막 값 ADJUSTMENT 만 적용되면 2)
    assert {m["movement_type"] for m in got["data"]} == {"SALE", "ADJUSTMENT"}
    out = client.get(MOVES, params={"movement_type": ["SALE", "DISPOSAL", "OTHER_OUT", "ADJUSTMENT"]}).json()  # 출고 화면이 쓸 묶음
    assert out["meta"]["total"] == 4 and {m["movement_type"] for m in out["data"]} == {"SALE", "DISPOSAL", "ADJUSTMENT"}
    assert client.get(MOVES, params={"movement_type": ["SALE", "SALE"]}).json()["meta"]["total"] == 1  # 같은 값을 두 번 보내도 한 번 센다


def test_movements_single_type_unchanged(client, world, data):
    """값이 하나일 때는 예전과 같다 (그 유형만, 기본 정렬)."""
    login_as(client)
    one = client.get(MOVES, params={"movement_type": "RECEIPT"})
    same = client.get(MOVES, params={"movement_type": ["RECEIPT"]})
    assert ids(one) == ids(same) and one.json()["meta"]["total"] == 2  # 회사 A 입고: p1 입고와 비활성 p3 입고
    assert {m["movement_type"] for m in one.json()["data"]} == {"RECEIPT"}


def test_movements_invalid_type_is_422(client, world, data):
    """잘못된 유형은 다른 값이 섞여 있어도 422 (조용히 무시하지 않는다)."""
    login_as(client)
    assert client.get(MOVES, params={"movement_type": "BOGUS"}).status_code == 422
    assert client.get(MOVES, params={"movement_type": ["SALE", "BOGUS"]}).status_code == 422
    assert client.get(MOVES, params={"sort": "newest"}).status_code == 422  # 정렬 옵션도 정해진 값만


def test_movements_sort_registered_puts_backdated_row_first(client, world, data, session):
    """등록순 정렬: 과거 입출고일로 방금 등록한 줄이 맨 위. 옵션을 안 쓰면 입출고일 순이라 맨 아래."""
    old = add_move(session, world, "a", data["p1"], "SALE", "OUT", 1, seoul_today() - timedelta(days=60))
    session.commit()  # 따로 확정해야 이전 줄들과 다른 등록 시각이 된다
    login_as(client)
    default = ids(client.get(MOVES, params={"product_id": data["p1"].id}))
    registered = ids(client.get(MOVES, params={"product_id": data["p1"].id, "sort": "registered"}))
    assert default[-1] == old.id  # 기본: 60일 전 입출고일이라 맨 아래
    assert registered[0] == old.id  # 등록순: 가장 나중에 등록했으니 맨 위
    assert sorted(default) == sorted(registered)  # 줄 구성은 같다
    assert ids(client.get(MOVES, params={"sort": "date"})) == ids(client.get(MOVES))  # sort=date 는 기본과 같다


def test_movements_sort_registered_uses_created_at_not_id(client, world, data, session):
    """등록순은 번호가 아니라 created_at 이 기준. 번호는 큰데 등록 시각이 더 이른 줄은 뒤로 간다."""
    first = add_move(session, world, "a", data["p2"], "SALE", "OUT", 1)
    second = add_move(session, world, "a", data["p2"], "SALE", "OUT", 2)
    second.created_at = first.created_at - timedelta(days=1)  # 번호는 second 가 크지만 등록 시각은 하루 이르다
    session.commit()
    login_as(client)
    assert ids(client.get(MOVES, params={"product_id": data["p2"].id, "sort": "registered"})) == [first.id, second.id]
    assert ids(client.get(MOVES, params={"product_id": data["p2"].id})) == [second.id, first.id]  # 기본 정렬은 같은 날 번호 큰 것 먼저


def test_movements_new_options_keep_company_isolation(client, world, data, session):
    """유형 여러 개·등록순을 써도 다른 회사 이력은 섞이지 않는다."""
    add_move(session, world, "b", data["b1"], "SALE", "OUT", 5)
    add_move(session, world, "b", data["b1"], "DISPOSAL", "OUT", 5)
    session.commit()
    login_as(client)
    got = client.get(MOVES, params={"movement_type": ["SALE", "DISPOSAL", "RECEIPT"], "sort": "registered", "page_size": 100}).json()
    assert all(m["product_id"] != data["b1"].id for m in got["data"])  # B 의 판매·폐기·입고(999) 모두 안 보임
    assert got["meta"]["total"] == 3  # A: 입고 2(p1, 비활성 p3) + 판매 1
    assert client.get(MOVES, params={"product_id": data["b1"].id, "movement_type": ["SALE", "DISPOSAL"]}).json()["meta"]["total"] == 0


def test_movements_new_options_with_paging(client, world, data, session):
    """유형 여러 개 + 등록순 + 쪽 나누기: 쪽마다 겹치거나 빠지는 줄이 없고 순서가 이어진다."""
    for qty in range(1, 6):  # 판매 5줄을 각각 확정해 등록 시각을 다르게
        add_move(session, world, "a", data["p2"], "SALE", "OUT", qty)
        session.commit()
    login_as(client)
    params = {"movement_type": ["SALE", "ADJUSTMENT"], "sort": "registered"}
    whole = client.get(MOVES, params={**params, "page_size": 100}).json()
    assert whole["meta"]["total"] == 8  # 판매 1 + 5, 조정 2
    pages = [client.get(MOVES, params={**params, "page_size": 3, "page": n}) for n in (1, 2, 3, 4)]
    assert [p.json()["meta"]["total"] for p in pages] == [8, 8, 8, 8]
    assert [len(p.json()["data"]) for p in pages] == [3, 3, 2, 0]
    assert [i for p in pages for i in ids(p)] == [m["id"] for m in whole["data"]]  # 쪽을 이어 붙이면 전체와 같다
