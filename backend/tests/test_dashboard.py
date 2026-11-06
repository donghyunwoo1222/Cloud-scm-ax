"""대시보드 API (#37) 테스트: GET /dashboard. 준비 데이터 world 는 conftest. 이력·발주는 표에 직접 넣는다(조회만 시험)."""

from datetime import date, timedelta  # 날짜 고정·이동

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from app.services.dashboard import DEAD_STOCK_DAYS  # 장기재고 기준(일)
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/dashboard"  # 대시보드 경로
N = DEAD_STOCK_DAYS  # 60
TODAY = seoul_today()  # 서울 기준 오늘


def add_product(session, world, key, sku, **fields):
    """품목 하나 (회사 key: a/b)."""
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=sku, unit="개", unit_cost=1000,
                default_supplier_id=world[f"{key}_supplier"].id, **fields)
    session.add(p)
    session.flush()  # id 받기
    return p


def add_move(session, world, key, product, mtype, direction, qty, day, reverses=None, po_item=None):
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


def add_po(session, world, key, number, status, product, qty, **fields):
    """발주서 한 장에 줄 하나 → 발주 줄 반환."""
    supplier_id = fields.pop("supplier_id", world[f"{key}_supplier"].id)
    order = PurchaseOrder(company_id=world[f"{key}_company"].id, supplier_id=supplier_id,
                          po_number=number, status=status, created_by=world[f"{key}_staff"].id, **fields)
    session.add(order)
    session.flush()
    line = PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=product.id,
                             quantity=qty, unit_price=1000)
    session.add(line)
    session.flush()
    return line


def get(client):
    """A 담당자로 로그인해 대시보드 조회 → data."""
    login_as(client)
    response = client.get(URL)
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def test_empty_company(client, world):
    """데이터가 하나도 없는 회사: 오류 없이 0과 빈 목록."""
    d = get(client)
    assert d["purchase_orders"] == {
        "draft": 0, "approved": 0, "ordered": 0, "incoming_quantity": 0, "incoming_by_unit": {},
        "due_today": 0, "overdue": 0,
    }
    assert d["month"]["in_quantity"] == 0 and d["month"]["out_quantity"] == 0
    assert d["dead_stock"]["count"] == 0 and d["dead_stock"]["items"] == [] and d["dead_stock"]["days"] == N


def test_requires_login(client, world):
    """로그인 없이는 401."""
    assert client.get(URL).status_code == 401


def test_open_orders_and_incoming(client, world, session):
    """상태별 건수와 입고 예정: ORDERED 100 중 입고 70 − 정정 10 = 60 입고 → 미입고 40. RECEIVED·CANCELLED 는 세지 않는다. 다른 회사 제외."""
    p = add_product(session, world, "a", "P1")
    q = add_product(session, world, "a", "P2")
    q.unit = "박스"  # 다른 단위는 따로 보여준다.
    b = add_product(session, world, "b", "B1")
    add_po(session, world, "a", "PO-1", "DRAFT", p, 5)
    add_po(session, world, "a", "PO-2", "APPROVED", p, 5)
    add_po(session, world, "a", "PO-3", "APPROVED", q, 5)
    line = add_po(session, world, "a", "PO-4", "ORDERED", p, 100)
    add_po(session, world, "a", "PO-5", "ORDERED", q, 30)  # 입고 없음 → 30 전부 미입고
    add_po(session, world, "a", "PO-6", "RECEIVED", p, 50)
    add_po(session, world, "a", "PO-7", "CANCELLED", p, 50)
    add_po(session, world, "b", "PO-B", "ORDERED", b, 999)  # 회사 B
    receipt = add_move(session, world, "a", p, "RECEIPT", "IN", 70, 3, po_item=line.id)
    add_move(session, world, "a", p, "CORRECTION", "OUT", 10, 3, reverses=receipt.id, po_item=line.id)
    session.commit()
    d = get(client)["purchase_orders"]
    assert d == {
        "draft": 1, "approved": 2, "ordered": 2, "incoming_quantity": 40 + 30,
        "incoming_by_unit": {"개": 40, "박스": 30}, "due_today": 0, "overdue": 0,
    }


def test_receipt_schedule_counts_match_filtered_orders(client, world, session, monkeypatch):
    """카드 건수와 목록이 날짜 경계·회사·발주 상태를 같은 방식으로 처리한다."""
    today = date(2026, 11, 6)
    monkeypatch.setattr("app.api.dashboard.seoul_today", lambda: today)
    monkeypatch.setattr("app.services.purchase_orders.seoul_today", lambda: today)
    product = add_product(session, world, "a", "SCHEDULE")
    foreign = add_product(session, world, "b", "FOREIGN")
    supplier = Supplier(company_id=product.company_id, name="다른 업체", lead_time_days=2)
    session.add(supplier)
    session.flush()
    late = add_po(session, world, "a", "LATE", "ORDERED", product, 30, due_date=today - timedelta(days=1))
    add_move(session, world, "a", product, "RECEIPT", "IN", 20, (TODAY - today).days, po_item=late.id)
    add_po(session, world, "a", "LATE2", "ORDERED", product, 1,
           due_date=today - timedelta(days=2), supplier_id=supplier.id)
    for name, days in (("TODAY", 0), ("TOMORROW", 1), ("DAY7", 7), ("DAY8", 8)):
        add_po(session, world, "a", name, "ORDERED", product, 1, due_date=today + timedelta(days=days))
    add_po(session, world, "a", "UNSCHEDULED", "ORDERED", product, 1)
    add_po(session, world, "a", "APPROVED", "APPROVED", product, 1, due_date=today)
    add_po(session, world, "a", "RECEIVED", "RECEIVED", product, 1, due_date=today)
    add_po(session, world, "b", "OTHER", "ORDERED", foreign, 1, due_date=today)
    session.commit()

    dashboard = get(client)["purchase_orders"]
    assert (dashboard["due_today"], dashboard["overdue"], dashboard["ordered"]) == (1, 2, 7)
    url = "/api/v1/purchase-orders"
    for period, expected in (
        ("TODAY", {"TODAY"}), ("OVERDUE", {"LATE", "LATE2"}),
        ("NEXT_7_DAYS", {"TOMORROW", "DAY7"}), ("UNSCHEDULED", {"UNSCHEDULED"}),
    ):
        response = client.get(url, params={"receipt_due": period})
        assert response.status_code == 200, response.json()
        assert {order["po_number"] for order in response.json()["data"]} == expected
    late_page = client.get(url, params={"receipt_due": "OVERDUE", "page_size": 1}).json()
    assert len(late_page["data"]) == 1 and late_page["meta"]["total"] == dashboard["overdue"]
    supplier_page = client.get(url, params={"receipt_due": "OVERDUE", "supplier_id": supplier.id}).json()
    assert [order["po_number"] for order in supplier_page["data"]] == ["LATE2"]
    search_page = client.get(url, params={"receipt_due": "OVERDUE", "q": "late2"}).json()
    assert [order["po_number"] for order in search_page["data"]] == ["LATE2"]
    assert client.get(url, params={"receipt_due": "BAD"}).status_code == 422


def test_month_movements_net_of_corrections(client, world, session):
    """이번 달 입고·출고: 입고 50, 판매 100 − 정정 90 = 10, 폐기 5 → 출고 15. 조정·지난달·미래 아님·다른 회사는 제외."""
    p = add_product(session, world, "a", "P1")
    b = add_product(session, world, "b", "B1")
    boxes = add_product(session, world, "a", "P2")
    boxes.unit = "박스"
    add_move(session, world, "a", boxes, "RECEIPT", "IN", 2, 0)
    month_day = TODAY.day - 1  # 이번 달 1일이면 0 → 오늘
    add_move(session, world, "a", p, "RECEIPT", "IN", 50, month_day)
    sale = add_move(session, world, "a", p, "SALE", "OUT", 100, month_day)
    add_move(session, world, "a", p, "CORRECTION", "IN", 90, month_day, reverses=sale.id)
    add_move(session, world, "a", p, "DISPOSAL", "OUT", 5, 0)
    add_move(session, world, "a", p, "ADJUSTMENT", "IN", 7, 0)  # 조정은 입고로 세지 않는다
    add_move(session, world, "a", p, "ADJUSTMENT", "OUT", 3, 0)  # 조정 정정도 출고로 세지 않는다
    add_move(session, world, "a", p, "RECEIPT", "IN", 1000, TODAY.day)  # 지난달 마지막 날 (TODAY − day일 = 전달 말일)
    add_move(session, world, "b", b, "RECEIPT", "IN", 777, 0)  # 회사 B
    session.commit()
    d = get(client)["month"]
    assert d["month_start"] == TODAY.replace(day=1).isoformat()
    assert d["month_end"] == TODAY.isoformat()
    assert d["in_count"] == 2 and d["out_count"] == 2  # 정정·조정은 새 입출고 건이 아니다
    assert d["in_quantity"] == 52 and d["out_quantity"] == 15
    assert d["in_by_unit"] == {"개": 50, "박스": 2}
    assert d["out_by_unit"] == {"개": 15}


# ----- 장기재고 -----
def test_dead_stock_boundary(client, world, session):
    """N=60: 마지막 판매가 정확히 60일 전이면 장기재고 아님, 61일 전이면 장기재고. 판매 없이 오래된 재고도 장기재고."""
    keep = add_product(session, world, "a", "KEEP")  # 60일 전 판매
    old = add_product(session, world, "a", "OLD")  # 61일 전 판매
    never = add_product(session, world, "a", "NEVER")  # 판매 없음
    for p in (keep, old, never):
        add_move(session, world, "a", p, "RECEIPT", "IN", 10, 200)  # 첫 입고는 충분히 오래전
    add_move(session, world, "a", keep, "SALE", "OUT", 1, N)
    add_move(session, world, "a", old, "SALE", "OUT", 1, N + 1)
    session.commit()
    d = get(client)["dead_stock"]
    assert {i["sku"] for i in d["items"]} == {"OLD", "NEVER"} and d["count"] == 2
    by = {i["sku"]: i for i in d["items"]}
    assert by["OLD"]["current_stock"] == 9 and by["OLD"]["last_sale_date"] == (TODAY - timedelta(days=N + 1)).isoformat()
    assert by["NEVER"]["last_sale_date"] is None


def test_dead_stock_excludes(client, world, session):
    """제외: 재고 0, 신규(첫 입출고 59일 전), 비활성, 다른 회사. 경계: 첫 입출고 정확히 60일 전은 포함."""
    zero = add_product(session, world, "a", "ZERO")
    fresh = add_product(session, world, "a", "FRESH")
    edge = add_product(session, world, "a", "EDGE")
    inactive = add_product(session, world, "a", "OFF", is_active=False)
    other = add_product(session, world, "b", "B1")
    add_move(session, world, "a", zero, "RECEIPT", "IN", 5, 200)
    add_move(session, world, "a", zero, "DISPOSAL", "OUT", 5, 100)  # 재고 0
    add_move(session, world, "a", fresh, "RECEIPT", "IN", 5, N - 1)
    add_move(session, world, "a", edge, "RECEIPT", "IN", 5, N)
    add_move(session, world, "a", inactive, "RECEIPT", "IN", 5, 200)
    add_move(session, world, "b", other, "RECEIPT", "IN", 5, 200)
    session.commit()
    assert [i["sku"] for i in get(client)["dead_stock"]["items"]] == ["EDGE"]


def test_dead_stock_net_sales(client, world, session):
    """순판매 반영: 5일 전 판매 100을 전량 정정하면 판매가 없던 것 → 장기재고. 정정 90이면 10이 남아 장기재고 아님."""
    full = add_product(session, world, "a", "FULL")  # 전량 정정된 최근 판매 → 판매 없음 취급
    partial = add_product(session, world, "a", "PART")  # 일부 정정, 최근 판매가 남음 → 장기재고 아님
    for p in (full, partial):
        add_move(session, world, "a", p, "RECEIPT", "IN", 500, 200)
    s1 = add_move(session, world, "a", full, "SALE", "OUT", 100, 5)
    add_move(session, world, "a", full, "CORRECTION", "IN", 100, 5, reverses=s1.id)
    s2 = add_move(session, world, "a", partial, "SALE", "OUT", 100, 5)
    add_move(session, world, "a", partial, "CORRECTION", "IN", 90, 5, reverses=s2.id)
    session.commit()
    assert [i["sku"] for i in get(client)["dead_stock"]["items"]] == ["FULL"]


def test_dead_stock_list_capped(client, world, session):
    """21개가 장기재고여도 목록은 20줄, count 는 21. 재고 많은 순."""
    for i in range(21):
        add_move(session, world, "a", add_product(session, world, "a", f"S{i:02d}"), "RECEIPT", "IN", i + 1, 200)
    session.commit()
    d = get(client)["dead_stock"]
    assert d["count"] == 21 and len(d["items"]) == 20
    assert d["items"][0]["current_stock"] == 21  # 가장 많은 재고가 맨 위


def test_overstock_ranks_before_preview_limit(client, world, session):
    """먼저 등록한 품목이어도 예상 소진일이 길면 목록 위에 남는다."""
    for index in range(21):
        product = add_product(session, world, "a", f"OVER-{index:02d}")
        add_move(session, world, "a", product, "RECEIPT", "IN", 150, 25)
        add_move(session, world, "a", product, "SALE", "OUT", 15 if index == 0 else 30, 1)
    session.commit()

    overstock = get(client)["overstock"]
    assert overstock["count"] == 21 and len(overstock["items"]) == 20
    assert overstock["items"][0]["sku"] == "OVER-00"


def test_company_isolation(client, world, session):
    """회사 B 에만 데이터가 있으면 A 대시보드는 비어 있다."""
    b = add_product(session, world, "b", "B1")
    add_move(session, world, "b", b, "RECEIPT", "IN", 5, 200)
    add_po(session, world, "b", "PO-B", "ORDERED", b, 10)
    session.commit()
    d = get(client)
    assert d["purchase_orders"]["ordered"] == 0 and d["dead_stock"]["count"] == 0 and d["month"]["in_quantity"] == 0
