"""재고 부족·과잉 표시 (#76) 테스트: GET /stock 의 상태, GET /dashboard 의 부족·과잉. 준비 데이터 world 는 conftest.

공통 조건(손 계산): 30일 판매 300 → 일평균 10, 리드타임 5(A업체), 안전재고 20 → 재주문점 10 × 5 + 20 = 70, 과잉 기준 10 × 90 = 900.
이력·발주는 표에 직접 넣는다(조회와 판정만 시험). 이력 헬퍼는 추천 조회 테스트(#39)와 같은 것을 쓴다.
"""

from datetime import date  # 순수 함수 테스트의 고정 날짜

from sqlalchemy import event  # 쿼리 횟수 세기

from app.models import Supplier  # 비활성 공급업체 만들기
from app.services.recommend import (  # 순수 함수 (#38, #76)
    calculate_recommendation,
    is_overstock,
    stock_status,
)
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import (  # 품목·이력·발주 넣기 (같은 헬퍼)
    OLD,
    add_move,
    add_po,
    add_product,
)

STOCK = "/api/v1/stock"  # 재고 목록 경로
DASH = "/api/v1/dashboard"  # 대시보드 경로


def with_stock(session, world, sku, stock, key="a", **fields):
    """공통 조건 품목: 40일 전 입고 (300 + stock), 어제 판매 300 → 현재고 stock, 일평균 10."""
    p = add_product(session, world, sku, key=key, **fields)
    add_move(session, world, p, "RECEIPT", "IN", 300 + stock, OLD, key=key)
    add_move(session, world, p, "SALE", "OUT", 300, 1, key=key)
    return p


def get(client, path, email="staff@a.test"):
    """로그인해 조회 → 응답 JSON 전체 (data·meta)."""
    login_as(client, email)
    response = client.get(path)
    assert response.status_code == 200, response.json()
    return response.json()


def rows(client, path=STOCK, email="staff@a.test"):
    """재고 목록을 SKU → 줄 딕셔너리로."""
    return {r["sku"]: r for r in get(client, path, email)["data"]}


def skus(section):
    """대시보드 부족·과잉 목록의 SKU 들."""
    return [i["sku"] for i in section["items"]]


# ----- 순수 함수: 경계 -----

def calc(stock, sales=300, in_transit=0):
    """공통 조건으로 계산 (오늘 11-05, 첫 입출고 40일 전, 리드타임 5, 안전재고 20)."""
    today = date(2026, 11, 5)
    return calculate_recommendation(today=today, first_movement_date=date(2026, 9, 26), supplier_active=True,
                                    sales_30d=sales, stock=stock, in_transit=in_transit, lead_time=5, safety_stock=20)


def test_status_boundary_by_hand():
    """현재고 50·70 → 부족(재주문점 70 이하), 71 → 정상. 진행 중 21 이면 50 도 가용 71 → 정상."""
    assert stock_status(calc(50)) == "SHORTAGE"
    assert stock_status(calc(70)) == "SHORTAGE"  # 정확히 재주문점이면 부족 (≤)
    assert stock_status(calc(71)) == "NORMAL"
    assert stock_status(calc(50, in_transit=21)) == "NORMAL"


def test_overstock_boundary_by_hand():
    """일평균 10 → 900(정확히 90일치)은 과잉, 899 는 아님. 판매 0(제외) 은 재고가 많아도 과잉이 아님."""
    assert is_overstock(900, calc(900)) is True
    assert is_overstock(899, calc(899)) is False
    assert is_overstock(10_000, calc(10_000, sales=0)) is False  # NO_SALES_30D 제외 → 과잉 아님
    assert stock_status(calc(10_000, sales=0)) == "UNKNOWN"


# ----- GET /stock -----

def test_stock_status_shortage_normal_and_fields(client, world, session):
    """S1 품목(현재고 50) 부족, 71 정상, 900 정상(과잉은 대시보드). 기존 칸은 그대로이고 새 칸이 붙는다."""
    s1 = with_stock(session, world, "S1", 50)
    with_stock(session, world, "N71", 71)
    with_stock(session, world, "O900", 900)
    session.commit()
    r = rows(client)
    assert r["S1"] == {"product_id": s1.id, "sku": "S1", "name": "S1 이름", "unit": "개", "safety_stock": 20,
                       "is_active": True, "current_stock": 50, "in_transit": 0, "status": "SHORTAGE", "status_reason": None}
    assert r["N71"]["status"] == "NORMAL" and r["O900"]["status"] == "NORMAL"


def test_ordered_releases_shortage_cancelled_does_not(client, world, session):
    """ORDERED 미입고 21 → 가용 71 → 정상(in_transit 21). CANCELLED 21 은 영향 없음 → 부족."""
    a = with_stock(session, world, "ORD", 50)
    add_po(session, world, "PO-1", "ORDERED", a, 21)
    b = with_stock(session, world, "CAN", 50)
    add_po(session, world, "PO-2", "CANCELLED", b, 21)
    session.commit()
    r = rows(client)
    assert r["ORD"]["in_transit"] == 21 and r["ORD"]["status"] == "NORMAL"
    assert r["CAN"]["in_transit"] == 0 and r["CAN"]["status"] == "SHORTAGE"


def test_excluded_products_unknown_with_reason(client, world, session):
    """계산 못 한 품목은 판단 불가 + 추천과 같은 이유 코드·문장 (데이터 부족·판매 없음·공급업체 비활성·이력 없음)."""
    p = add_product(session, world, "NEW")
    add_move(session, world, p, "RECEIPT", "IN", 50, 10)  # 첫 입고 10일 전 (14일 미만)
    q = add_product(session, world, "NOSALE")
    add_move(session, world, q, "RECEIPT", "IN", 50, OLD)
    off = Supplier(company_id=world["a_company"].id, name="꺼진업체", lead_time_days=5, is_active=False)
    session.add(off)
    session.flush()
    with_stock(session, world, "OFF", 50, supplier=off)
    add_product(session, world, "EMPTY")  # 이력 없음
    session.commit()
    r = rows(client)
    assert r["NEW"]["status"] == "UNKNOWN" and r["NEW"]["status_reason"] == {"code": "INSUFFICIENT_DATA", "message": "데이터 부족"}
    assert r["NOSALE"]["status_reason"]["code"] == "NO_SALES_30D"
    assert r["OFF"]["status_reason"]["code"] == "MISSING_INFO"
    assert r["EMPTY"]["status"] == "UNKNOWN" and r["EMPTY"]["current_stock"] == 0


def test_inactive_product_hidden_or_no_status(client, world, session):
    """비활성 품목은 기본 숨김. 포함해서 보면 상태는 null(계산하지 않음), 상태로 거르면 나오지 않는다."""
    with_stock(session, world, "OFF-P", 50, is_active=False)  # 활성이면 부족일 품목
    session.commit()
    assert "OFF-P" not in rows(client)
    r = rows(client, f"{STOCK}?include_inactive=true")["OFF-P"]
    assert r["status"] is None and r["status_reason"] is None and r["current_stock"] == 50
    assert get(client, f"{STOCK}?status=SHORTAGE&include_inactive=true")["data"] == []


def test_status_filter_counts_whole_company_then_pages(client, world, session):
    """필터가 있으면 전체를 계산한 뒤 거르고 쪽을 자른다: 정상 25개 + 부족 3개 → 1쪽(2개씩)에 부족 2개, total 3."""
    short = [with_stock(session, world, f"SH{k}", 50) for k in range(3)]
    for k in range(25):
        with_stock(session, world, f"OK{k}", 200)
    session.commit()
    first = get(client, f"{STOCK}?status=SHORTAGE&page_size=2")
    assert first["meta"] == {"page": 1, "page_size": 2, "total": 3}
    assert [r["sku"] for r in first["data"]] == ["SH2", "SH1"]  # 최신 품목 먼저
    assert [r["sku"] for r in get(client, f"{STOCK}?status=SHORTAGE&page_size=2&page=2")["data"]] == ["SH0"]
    assert get(client, f"{STOCK}?status=NORMAL")["meta"]["total"] == 25
    assert all(r["status"] == "SHORTAGE" for r in first["data"]) and short


def test_status_filter_rejects_unknown_value(client, world):
    """정해진 상태 값이 아니면 422."""
    login_as(client)
    assert client.get(f"{STOCK}?status=LOW").status_code == 422


def test_stock_one_has_status(client, world, session):
    """GET /stock/{id} 도 같은 상태를 준다. 다른 회사 품목은 404."""
    a = with_stock(session, world, "ONE", 50)
    b = with_stock(session, world, "B-ONE", 50, key="b")
    session.commit()
    body = get(client, f"{STOCK}/{a.id}")["data"]
    assert body["status"] == "SHORTAGE" and body["in_transit"] == 0
    assert client.get(f"{STOCK}/{b.id}").status_code == 404


def test_company_isolation(client, world, session):
    """회사 A 로 로그인하면 B 품목이 안 보이고, B 의 진행 중 발주가 A 판정에 섞이지 않는다."""
    with_stock(session, world, "A-ITEM", 50)
    b = with_stock(session, world, "B-ITEM", 50, key="b")
    add_po(session, world, "PO-B", "ORDERED", b, 999, key="b")
    session.commit()
    r = rows(client)
    assert list(r) == ["A-ITEM"] and r["A-ITEM"]["status"] == "SHORTAGE"
    assert rows(client, email="staff@b.test")["B-ITEM"]["status"] == "NORMAL"
    assert skus(get(client, DASH)["data"]["shortage"]) == ["A-ITEM"]


def test_empty_company(client, world):
    """데이터가 하나도 없는 회사: 재고 목록은 비고, 대시보드 부족·과잉은 0."""
    assert get(client, STOCK) == {"data": [], "meta": {"page": 1, "page_size": 20, "total": 0}}
    assert get(client, f"{STOCK}?status=SHORTAGE")["meta"]["total"] == 0
    d = get(client, DASH)["data"]
    assert d["shortage"] == {"count": 0, "items": []}
    assert d["overstock"] == {"days": 90, "count": 0, "items": []}


# ----- GET /dashboard -----

def test_dashboard_shortage_and_overstock(client, world, session):
    """부족: 현재고 50(재주문점 70). 과잉: 900 포함, 899·판매 없는 10,000 은 아님. 기존 칸(장기재고 등)도 그대로."""
    s1 = with_stock(session, world, "S1", 50)
    with_stock(session, world, "O900", 900)
    with_stock(session, world, "O899", 899)
    nosale = add_product(session, world, "NOSALE")
    add_move(session, world, nosale, "RECEIPT", "IN", 10_000, OLD)
    session.commit()
    d = get(client, DASH)["data"]
    assert {"purchase_orders", "month", "dead_stock"} <= set(d)  # 기존 칸 유지
    assert d["shortage"] == {"count": 1, "items": [{
        "product_id": s1.id, "sku": "S1", "name": "S1 이름", "unit": "개", "current_stock": 50,
        "available": 50, "reorder_point": 70.0, "recommended_quantity": 160,
    }]}
    assert d["overstock"]["count"] == 1 and skus(d["overstock"]) == ["O900"]
    assert d["overstock"]["items"][0]["avg_daily_sales"] == 10.0


def test_dashboard_lists_capped_at_20(client, world, session):
    """부족 25개 → 목록 20줄, count 25."""
    for k in range(25):
        with_stock(session, world, f"SH{k}", 50)
    session.commit()
    s = get(client, DASH)["data"]["shortage"]
    assert s["count"] == 25 and len(s["items"]) == 20


def test_dead_stock_and_overstock_do_not_overlap(client, world, session):
    """장기재고(60일 넘게 판매 없음)와 과잉(최근 30일 판매 필요)은 같은 품목에 함께 나오지 않는다."""
    dead = add_product(session, world, "DEAD")
    add_move(session, world, dead, "RECEIPT", "IN", 10_000, 100)
    add_move(session, world, dead, "SALE", "OUT", 300, 70)  # 70일 전 판매 → 장기재고, 30일 판매 0 → 과잉 아님
    with_stock(session, world, "OVER", 10_000)  # 어제 판매 → 과잉, 장기재고 아님
    session.commit()
    d = get(client, DASH)["data"]
    assert skus(d["dead_stock"]) == ["DEAD"] and skus(d["overstock"]) == ["OVER"]


def test_query_count_same_for_3_and_30_products(client, world, session, engine):
    """품목 3개와 30개의 쿼리 횟수가 같다: 재고 목록(필터 없음·있음), 한 건, 대시보드 각각."""
    def count_queries(n, path, tag):
        for k in range(n):  # 이력·발주가 모두 있는 품목 n개를 더 넣는다
            p = with_stock(session, world, f"Q{tag}-{n}-{k}", 50)
            add_po(session, world, f"PO-{tag}-{n}-{k}", "ORDERED", p, 10)
        session.commit()
        login_as(client)
        seen = []  # 실행된 SQL
        listener = lambda *args: seen.append(args[2])  # before_cursor_execute 의 SQL 문장을 모은다
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert client.get(path).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    for tag, path in enumerate((f"{STOCK}?page_size=100", f"{STOCK}?status=SHORTAGE&page_size=100", DASH)):
        assert count_queries(3, path, tag) == count_queries(30, path, tag), path  # tag: 경로마다 SKU 가 겹치지 않게
