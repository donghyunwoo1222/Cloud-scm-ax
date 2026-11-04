"""추천 조회 API (#39) 테스트: GET /recommendations. 준비 데이터 world 는 conftest(A업체·B업체 리드타임 5).

시나리오 번호는 docs/04-ax-design/ax-design.md "1단계: 정답 시나리오". 공통 조건: 30일 판매 300(일평균 10), 리드타임 5, 안전재고 20.
이력·발주는 표에 직접 넣는다(조회와 계산만 시험). 첫 입고는 40일 전에 넣어 데이터 부족(14일)과 30일 판매 기간 밖에 둔다.
"""

from datetime import timedelta  # 날짜 빼기

from sqlalchemy import event  # 쿼리 횟수 세기

from app.clock import seoul_today  # 서울 기준 오늘 (API 도 같은 값을 쓴다)
from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/recommendations"  # 추천 조회 경로
TODAY = seoul_today()  # 서울 기준 오늘
OLD = 40  # 첫 입고를 넣는 날 (오늘로부터 40일 전)


def add_product(session, world, sku, key="a", safety_stock=20, supplier=None, **fields):
    """품목 하나 (기본: 회사 A, 안전재고 20, 기본 공급업체 A업체)."""
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=f"{sku} 이름", unit="개", unit_cost=1000,
                default_supplier_id=(supplier or world[f"{key}_supplier"]).id, safety_stock=safety_stock, **fields)
    session.add(p)
    session.flush()  # id 받기
    return p


def add_move(session, world, product, mtype, direction, qty, day, key="a", reverses=None, po_item=None):
    """이력 한 줄 (day 는 오늘로부터 며칠 전인지)."""
    m = InventoryMovement(
        company_id=world[f"{key}_company"].id, product_id=product.id, created_by=world[f"{key}_staff"].id,
        movement_type=mtype, direction=direction, quantity=qty, movement_date=TODAY - timedelta(days=day),
        sales_channel="OWN_MALL" if mtype == "SALE" else None,
        reason="사유" if mtype in ("ADJUSTMENT", "CORRECTION") else None, reverses_movement_id=reverses,
        purchase_order_item_id=po_item,
    )
    session.add(m)
    session.flush()
    return m


def add_po(session, world, number, status, product, qty, key="a"):
    """발주서 한 장에 줄 하나 → 발주 줄 반환."""
    order = PurchaseOrder(company_id=world[f"{key}_company"].id, supplier_id=world[f"{key}_supplier"].id,
                          po_number=number, status=status, created_by=world[f"{key}_staff"].id)
    session.add(order)
    session.flush()
    line = PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=product.id,
                             quantity=qty, unit_price=1000)
    session.add(line)
    session.flush()
    return line


def stock_50_sold_300(session, world, sku, key="a", **fields):
    """공통 조건 품목: 40일 전 입고 350, 어제 판매 300 → 현재고 50, 30일 판매 300(일평균 10)."""
    p = add_product(session, world, sku, key=key, **fields)
    add_move(session, world, p, "RECEIPT", "IN", 350, OLD, key=key)
    add_move(session, world, p, "SALE", "OUT", 300, 1, key=key)
    return p


def get(client, email="staff@a.test"):
    """로그인해 추천 조회 → data."""
    login_as(client, email)
    response = client.get(URL)
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def item(data, sku):
    """추천 목록에서 SKU 로 한 줄 찾기 (없으면 None)."""
    return next((i for i in data["items"] if i["product_sku"] == sku), None)


def excluded(data, sku):
    """제외 목록에서 SKU 로 한 줄 찾기 (없으면 None)."""
    return next((e for e in data["excluded"] if e["product_sku"] == sku), None)


# ----- 정답 시나리오 -----

def test_s1_shortage_recommends_160(client, world, session):
    """S1: 현재고 50, 진행 0 → 재주문점 70, 추천 160. 응답 칸 모양도 확인."""
    p = stock_50_sold_300(session, world, "S1")
    session.commit()
    assert get(client)["items"] == [{
        "product_id": p.id, "product_sku": "S1", "product_name": "S1 이름",
        "supplier_id": world["a_supplier"].id, "supplier_name": "A업체",
        "current_stock": 50, "in_transit": 0, "available": 50,
        "avg_daily_sales": 10.0, "lead_time_days": 5, "safety_stock": 20, "reorder_point": 70.0,
        "recommended_quantity": 160,
        "reason": "최근 30일 하루 평균 10개가 팔렸고 리드타임은 5일입니다. 리드타임 동안 50개가 필요하고 "
                  "안전재고 20개를 더하면 70개입니다. 지금 가용재고는 50개라서 발주를 추천합니다. 추천 수량은 160개입니다.",
    }]


def test_s2_enough_stock_not_listed(client, world, session):
    """S2: 현재고 150 > 70 → 추천 없음 (제외 목록에도 없다)."""
    p = add_product(session, world, "S2")
    add_move(session, world, p, "RECEIPT", "IN", 450, OLD)
    add_move(session, world, p, "SALE", "OUT", 300, 1)
    session.commit()
    assert get(client) == {"items": [], "excluded": []}


def test_s3_ordered_counts_as_available(client, world, session):
    """S3: 현재고 50 + ORDERED 160 → 가용재고 210 > 70, 추천 없음."""
    p = stock_50_sold_300(session, world, "S3")
    add_po(session, world, "PO-1", "ORDERED", p, 160)
    session.commit()
    assert get(client)["items"] == []


def test_s4_cancelled_order_not_counted(client, world, session):
    """S4: CANCELLED 160 은 진행 중이 아니다 → 진행 0, 추천 160. DRAFT·APPROVED·RECEIVED 도 넣지 않는다."""
    p = stock_50_sold_300(session, world, "S4")
    for n, status in enumerate(("CANCELLED", "DRAFT", "APPROVED", "RECEIVED")):
        add_po(session, world, f"PO-{n}", status, p, 160)
    session.commit()
    row = item(get(client), "S4")
    assert row["in_transit"] == 0 and row["recommended_quantity"] == 160


def test_s5_no_sales_excluded(client, world, session):
    """S5: 30일 판매 0 → excluded NO_SALES_30D, "최근 30일 판매 없음"."""
    p = add_product(session, world, "S5")
    add_move(session, world, p, "RECEIPT", "IN", 50, OLD)
    session.commit()
    assert get(client)["excluded"] == [{"product_id": p.id, "product_sku": "S5", "product_name": "S5 이름",
                                        "code": "NO_SALES_30D", "message": "최근 30일 판매 없음"}]


def test_s6_insufficient_data_excluded(client, world, session):
    """S6: 첫 입출고 13일 전 → INSUFFICIENT_DATA. 이력이 하나도 없는 품목도 INSUFFICIENT_DATA."""
    p = add_product(session, world, "S6")
    add_move(session, world, p, "RECEIPT", "IN", 350, 13)
    add_move(session, world, p, "SALE", "OUT", 300, 1)
    add_product(session, world, "EMPTY")  # 이력 없음
    session.commit()
    d = get(client)
    assert excluded(d, "S6")["code"] == "INSUFFICIENT_DATA" and excluded(d, "S6")["message"] == "데이터 부족"
    assert excluded(d, "EMPTY")["code"] == "INSUFFICIENT_DATA"


def test_s7_inactive_supplier_missing_info(client, world, session):
    """S7: 기본 공급업체 비활성 → MISSING_INFO 와 안내 문장 (품목은 활성)."""
    off = Supplier(company_id=world["a_company"].id, name="꺼진업체", lead_time_days=5, is_active=False)
    session.add(off)
    session.flush()
    stock_50_sold_300(session, world, "S7", supplier=off)
    session.commit()
    e = excluded(get(client), "S7")
    assert e["code"] == "MISSING_INFO" and e["message"] == "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요"


def test_s8_company_isolation(client, world, session):
    """S8: 회사 A 로 로그인하면 회사 B 품목은 보이지 않고, B 의 판매·발주가 A 계산에 섞이지 않는다."""
    a = stock_50_sold_300(session, world, "A-ITEM")
    b = stock_50_sold_300(session, world, "B-ITEM", key="b")
    add_po(session, world, "PO-B", "ORDERED", b, 999, key="b")  # B 의 진행 중 발주
    session.commit()
    d = get(client)
    assert [i["product_sku"] for i in d["items"]] == ["A-ITEM"] and d["excluded"] == []
    assert item(d, "A-ITEM")["product_id"] == a.id and item(d, "A-ITEM")["recommended_quantity"] == 160
    assert get(client, "staff@b.test")["items"] == []  # B 는 999 가 오는 중이라 추천 없음, A 품목도 없음


def test_s13_sale_correction_subtracted(client, world, session):
    """S13: SALE 100 + 그 SALE 의 정정 90 → 30일 판매 10 (일평균 0.333…).

    안전재고 50, 현재고 50 − 100 + 90 = 40 → 재주문점 10/30 × 5 + 50 = 51.67, 추천 10/30 × 19 + 50 − 40 = 16.33 → 17.
    """
    p = add_product(session, world, "S13", safety_stock=50)
    add_move(session, world, p, "RECEIPT", "IN", 50, OLD)
    sale = add_move(session, world, p, "SALE", "OUT", 100, 1)
    add_move(session, world, p, "CORRECTION", "IN", 90, 1, reverses=sale.id)
    session.commit()
    row = item(get(client), "S13")
    assert row["avg_daily_sales"] == 10 / 30 and row["current_stock"] == 40 and row["recommended_quantity"] == 17


# ----- 섞인 이력과 경계 -----

def test_mixed_history_matches_hand_calculation(client, world, session):
    """입출고·정정·조정·부분 입고 발주가 섞인 품목. 안전재고 100.

    현재고 = 입고 320 − 판매 300 − 판매 30 + 판매 정정 30 − 폐기 5 + 폐기 정정 2 − 조정 3 + 발주 입고 40 − 입고 정정 10 = 44
    30일 판매 = 300 + 30 − 30 = 300 (폐기·폐기 정정·조정은 판매와 무관) → 일평균 10
    진행 중 = ORDERED 100 − (입고 40 − 정정 10) = 70 (APPROVED 50 은 넣지 않음) → 가용재고 114
    재주문점 = 10 × 5 + 100 = 150, 114 ≤ 150 → 추천 = 10 × 19 + 100 − 114 = 176
    """
    p = add_product(session, world, "MIX", safety_stock=100)
    add_move(session, world, p, "RECEIPT", "IN", 320, OLD)
    add_move(session, world, p, "SALE", "OUT", 300, 2)
    wrong = add_move(session, world, p, "SALE", "OUT", 30, 3)
    add_move(session, world, p, "CORRECTION", "IN", 30, 3, reverses=wrong.id)  # 판매 전량 정정
    disposal = add_move(session, world, p, "DISPOSAL", "OUT", 5, 2)
    add_move(session, world, p, "CORRECTION", "IN", 2, 2, reverses=disposal.id)  # 폐기 정정 (판매에서 빼면 안 된다)
    add_move(session, world, p, "ADJUSTMENT", "OUT", 3, 1)
    line = add_po(session, world, "PO-1", "ORDERED", p, 100)
    receipt = add_move(session, world, p, "RECEIPT", "IN", 40, 1, po_item=line.id)  # 부분 입고
    add_move(session, world, p, "CORRECTION", "OUT", 10, 1, reverses=receipt.id, po_item=line.id)  # 입고 정정
    add_po(session, world, "PO-2", "APPROVED", p, 50)
    session.commit()
    row = item(get(client), "MIX")
    assert (row["current_stock"], row["in_transit"], row["available"]) == (44, 70, 114)
    assert (row["avg_daily_sales"], row["reorder_point"], row["recommended_quantity"]) == (10.0, 150.0, 176)


def test_30_day_window_boundary(client, world, session):
    """오늘−29일 판매는 포함, 오늘−30일 판매는 제외. 판매 30(29일 전) + 999(30일 전) → 30일 판매 30, 일평균 1.

    현재고 1029 − 30 − 999 = 0, 재주문점 1 × 5 + 20 = 25 → 추천 1 × 19 + 20 − 0 = 39.
    """
    p = add_product(session, world, "EDGE")
    add_move(session, world, p, "RECEIPT", "IN", 1029, OLD)
    add_move(session, world, p, "SALE", "OUT", 30, 29)
    add_move(session, world, p, "SALE", "OUT", 999, 30)
    session.commit()
    row = item(get(client), "EDGE")
    assert row["avg_daily_sales"] == 1.0 and row["recommended_quantity"] == 39


def test_inactive_product_not_listed(client, world, session):
    """비활성 품목은 부족해도 추천·제외 목록 어디에도 없다."""
    stock_50_sold_300(session, world, "OFF", is_active=False)
    session.commit()
    assert get(client) == {"items": [], "excluded": []}


def test_empty_company(client, world):
    """데이터가 하나도 없는 회사: 오류 없이 빈 목록."""
    assert get(client) == {"items": [], "excluded": []}


def test_requires_login(client, world):
    """로그인 없이는 401."""
    assert client.get(URL).status_code == 401


def test_query_count_same_for_3_and_30_products(client, world, session, engine):
    """품목 3개와 30개의 쿼리 횟수가 같다 (품목마다 따로 묻지 않는다, N+1 없음)."""
    def count_queries(n):
        for k in range(n):  # 이력·발주가 모두 있는 품목 n개를 더 넣는다
            p = stock_50_sold_300(session, world, f"Q{n}-{k}")
            add_po(session, world, f"PO-{n}-{k}", "ORDERED", p, 10)
        session.commit()
        login_as(client)
        seen = []  # 실행된 SQL
        listener = lambda *args: seen.append(args[2])  # before_cursor_execute(conn, cursor, statement, ...) 의 SQL 문장을 모은다
        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert client.get(URL).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    assert count_queries(3) == count_queries(30)
