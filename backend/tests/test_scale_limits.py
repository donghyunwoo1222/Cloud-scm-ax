"""규모 제한 해제 (#184 PR 1) 테스트: 쪽 순회로 끝까지 닿기, 추천의 draft 필드, 줄 수·품목 수 서버 상한.

100개를 넘는 데이터(업체 150곳, 초안 150장, 품목 150개)에서도 틀리지 않는지, 상한 경계(2,000 통과·2,001 거절,
1,000 통과·1,001 거절)와 합친 뒤 총 줄 수 검사를 확인한다. 준비 도구는 #39 테스트 파일의 것을 쓴다.
"""

from datetime import timedelta  # 날짜 빼기

from sqlalchemy import func, select  # 개수 세기

from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import OLD, TODAY, stock_50_sold_300  # 준비 도구

PO = "/api/v1/purchase-orders"  # 발주 경로
REC = "/api/v1/recommendations"  # 추천 경로


def read_all(client, path):
    """100씩 끝까지 읽어 (모든 행, 마지막 meta) 를 돌려준다 (화면의 apiListAll 과 같은 방식)."""
    rows, page = [], 1
    while True:
        body = client.get(path, params={"page_size": 100, "page": page}).json()
        rows += body["data"]
        if not body["data"] or page * body["meta"]["page_size"] >= body["meta"]["total"]:
            return rows, body["meta"]
        page += 1


def bulk_products(session, world, n, prefix, key="a", supplier=None):
    """품목 n개를 한 번에 넣는다 (기본 공급업체 지정). 줄마다 flush 하지 않아 빠르다."""
    sup = supplier or world[f"{key}_supplier"]
    items = [Product(company_id=world[f"{key}_company"].id, sku=f"{prefix}{i}", name=f"{prefix}{i}", unit="개",
                     unit_cost=1000, default_supplier_id=sup.id, safety_stock=20) for i in range(n)]
    session.add_all(items)
    session.flush()
    return items


def recommended_products(session, world, n, prefix):
    """추천 대상 품목 n개 (40일 전 입고 350, 어제 판매 300 → 현재고 50, 추천 160)를 한 번에 만든다."""
    items = bulk_products(session, world, n, prefix)
    rows = []
    for p in items:
        for mtype, direction, qty, day in (("RECEIPT", "IN", 350, OLD), ("SALE", "OUT", 300, 1)):
            rows.append(InventoryMovement(
                company_id=p.company_id, product_id=p.id, created_by=world["a_staff"].id, movement_type=mtype,
                direction=direction, quantity=qty, movement_date=TODAY - timedelta(days=day),
                sales_channel="OWN_MALL" if mtype == "SALE" else None))
    session.add_all(rows)
    session.flush()
    return items


def draft_for(session, world, supplier, product, key="a", po_number=None):
    """공급업체의 DRAFT 발주서 한 장에 품목 줄 하나."""
    order = PurchaseOrder(company_id=world[f"{key}_company"].id, supplier_id=supplier.id, status="DRAFT",
                          po_number=po_number or f"PO-{supplier.id}", created_by=world[f"{key}_staff"].id)
    session.add(order)
    session.flush()
    session.add(PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=product.id,
                                  quantity=10, unit_price=1000))
    session.flush()
    return order


# ----- 끝까지 닿기: 100개를 넘어도 쪽 순회로 모두 읽힌다 -----
def test_suppliers_150_all_reachable_and_isolated(client, world, session):
    session.add_all(Supplier(company_id=world["a_company"].id, name=f"업체{i:03d}", lead_time_days=3) for i in range(150))
    session.commit()
    login_as(client)
    rows, meta = read_all(client, "/api/v1/suppliers")
    assert meta["total"] == 151 == len(rows) == len({r["id"] for r in rows})  # world 의 A업체 1 + 150, 중복·누락 없음
    assert world["b_supplier"].id not in {r["id"] for r in rows}  # 다른 회사 업체는 안 섞인다


def test_products_150_all_reachable(client, world, session):
    bulk_products(session, world, 150, "ALL-")
    session.commit()
    login_as(client)
    rows, meta = read_all(client, "/api/v1/products")
    assert meta["total"] == len(rows) == 150 and len({r["id"] for r in rows}) == 150


# ----- 추천 응답의 draft: 초안 150장에서도 정확 -----
def test_draft_field_correct_with_150_drafts(client, world, session):
    suppliers = [Supplier(company_id=world["a_company"].id, name=f"업체{i}", lead_time_days=3) for i in range(150)]
    session.add_all(suppliers)
    session.flush()
    products = [stock_50_sold_300(session, world, f"D-{i}", supplier=s) for i, s in enumerate(suppliers)]
    orders = [draft_for(session, world, s, p, po_number=f"PO-D-{i:03d}") for i, (s, p) in enumerate(zip(suppliers, products))]
    session.commit()
    login_as(client)
    items = {i["product_id"]: i for i in client.get(REC).json()["data"]["items"]}
    assert len(items) == 150
    for product, order in zip(products, orders):
        d = items[product.id]["draft"]
        assert d["purchase_order_id"] == order.id and d["po_number"] == order.po_number and d["quantity"] == 10
        assert d["box_quantity"] is None  # 박스 설정 없는 줄


def test_draft_field_null_without_draft_and_ignores_non_draft(client, world, session):
    p = stock_50_sold_300(session, world, "ND-1")
    q = stock_50_sold_300(session, world, "ND-2")
    order = draft_for(session, world, world["a_supplier"], q)
    order.status = "APPROVED"  # 초안이 아니면 "초안에 있음"이 아니다
    session.commit()
    login_as(client)
    items = {i["product_id"]: i for i in client.get(REC).json()["data"]["items"]}
    assert items[p.id]["draft"] is None and items[q.id]["draft"] is None
    assert "recommended_order_units" in items[p.id] and "recommended_quantity" in items[p.id]  # 기존 칸은 그대로


def test_draft_field_never_shows_other_company_draft(client, world, session):
    """다른 회사의 초안이 (같은 품목 번호를 가리켜도) 내 추천의 draft 로 나오지 않는다 — 쿼리의 회사 조건을 증명."""
    mine = stock_50_sold_300(session, world, "ISO-A")
    theirs = stock_50_sold_300(session, world, "ISO-B", key="b")
    b_second = Supplier(company_id=world["b_company"].id, name="B둘째", lead_time_days=3)  # 업체당 초안 1장이라 업체를 하나 더 둔다
    session.add(b_second)
    session.flush()
    draft_for(session, world, b_second, mine, key="b", po_number="PO-B-1")  # B 의 초안이 A 의 품목을 가리키게 직접 넣는다(API 로는 못 만든다)
    draft_for(session, world, world["b_supplier"], theirs, key="b", po_number="PO-B-2")
    session.commit()
    login_as(client)
    a_items = {i["product_id"]: i for i in client.get(REC).json()["data"]["items"]}
    assert a_items[mine.id]["draft"] is None  # A 는 B 의 초안을 못 본다
    login_as(client, "staff@b.test")
    b_items = {i["product_id"]: i for i in client.get(REC).json()["data"]["items"]}
    assert b_items[theirs.id]["draft"]["po_number"] == "PO-B-2" and mine.id not in b_items  # B 도 자기 것만


# ----- 줄 수 상한 (발주서 2,000줄) -----
def test_order_lines_2000_ok_and_2001_rejected(client, world, session):
    products = bulk_products(session, world, 2000, "LN-")
    session.commit()
    login_as(client)
    line = lambda pid: {"product_id": pid, "quantity": 1, "unit_price": 100}
    body = {"supplier_id": world["a_supplier"].id, "items": [line(p.id) for p in products]}
    r = client.post(PO, json=body)
    assert r.status_code == 201 and len(r.json()["data"]["items"]) == 2000  # 경계: 2,000줄 통과
    too_many = [line(p.id) for p in products] + [line(products[0].id + 100000)]
    assert client.post(PO, json={**body, "items": too_many}).status_code == 422  # 2,001줄 거절
    r = client.patch(f"{PO}/{r.json()['data']['id']}", json={"items": too_many})
    assert r.status_code == 422  # 수정도 같은 상한


# ----- 추천 초안 1회 상한 (1,000품목) -----
def test_draft_request_1000_ok_and_1001_rejected(client, world, session):
    products = recommended_products(session, world, 1000, "R1K-")
    session.commit()
    login_as(client)
    items = [{"product_id": p.id, "quantity": 160} for p in products]
    over = client.post(f"{REC}/drafts", json={"items": items + [{"product_id": products[-1].id + 100000}]})
    assert over.status_code == 422  # 1,001개 거절 (아무것도 만들지 않는다)
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0
    ok = client.post(f"{REC}/drafts", json={"items": items})
    assert ok.status_code == 201, ok.json()
    assert len(ok.json()["data"][0]["items"]) == 1000  # 경계: 1,000개 통과 (같은 업체라 초안 1장)


# ----- 합친 뒤 총 줄 수 상한 -----
def test_existing_draft_plus_new_lines_over_2000_rejected(client, world, session):
    old = bulk_products(session, world, 1500, "OLD-")  # 이미 초안에 든 1,500줄 (추천 대상 아님)
    order = PurchaseOrder(company_id=world["a_company"].id, supplier_id=world["a_supplier"].id, status="DRAFT",
                          po_number="PO-BIG", created_by=world["a_staff"].id)
    session.add(order)
    session.flush()
    session.add_all(PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=p.id,
                                      quantity=1, unit_price=1) for p in old)
    new = recommended_products(session, world, 600, "NEW-")
    session.commit()
    login_as(client)
    r = client.post(f"{REC}/drafts", json={"items": [{"product_id": p.id, "quantity": 160} for p in new]})  # 1500 + 600 = 2100
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR" and "PO-BIG" in r.json()["error"]["message"]
    count = lambda: session.scalar(select(func.count()).select_from(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order.id))
    session.expire_all()
    assert count() == 1500  # 거절되면 하나도 바뀌지 않는다
    ok = client.post(f"{REC}/drafts", json={"items": [{"product_id": p.id, "quantity": 160} for p in new[:500]]})  # 1500 + 500 = 2000 경계 통과
    assert ok.status_code == 201, ok.json()
    session.expire_all()
    assert count() == 2000
