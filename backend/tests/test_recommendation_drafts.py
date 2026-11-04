"""추천으로 초안 만들기 (#40) 테스트: POST /recommendations/drafts.

공통 조건(ax-design.md): 30일 판매 300(일평균 10), 리드타임 5(A업체), 안전재고 20, 현재고 50 → 추천 160.
준비 도구(add_product·add_move·add_po·stock_50_sold_300)는 #39 테스트 파일의 것을 쓴다. 담당자(staff@a.test)로 호출한다(권한: 둘 다 허용).
"""

from datetime import timedelta  # 날짜 더하기

from sqlalchemy import func, select  # 개수 세기

from app.errors import AppError  # 업무 오류
from app.models import (  # 표
    Company,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.schemas.recommendations import DraftCreate  # 요청 모양
from app.services import recommendations as recommendation_service  # 초안 만들기
from tests.concurrency import (  # 동시 요청 도구
    delayed,
    hold_row_lock,
    run_at_once,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import (  # 준비 도구
    TODAY,
    add_move,
    add_po,
    add_product,
    stock_50_sold_300,
)

URL = "/api/v1/recommendations/drafts"  # 초안 만들기 경로


def post(client, items):
    """담당자로 로그인해 초안 만들기 → 응답."""
    login_as(client)
    return client.post(URL, json={"items": items})


def drafts(session, world):
    """회사 A 의 DRAFT 발주서 수."""
    return session.scalar(select(func.count()).select_from(PurchaseOrder).where(
        PurchaseOrder.company_id == world["a_company"].id, PurchaseOrder.status == "DRAFT"))


# ----- 정답 시나리오 S9·S10 -----

def test_s9_same_supplier_two_items_one_draft(client, world, session):
    """S9: 같은 공급업체 품목 2개 → DRAFT 1장, 품목 2줄. 수량은 사용자가 고친 값, 추천 수량·이유는 서버가 다시 계산한 160."""
    p1 = stock_50_sold_300(session, world, "S9-1")
    p2 = stock_50_sold_300(session, world, "S9-2")
    session.commit()
    r = post(client, [{"product_id": p1.id, "quantity": 150}, {"product_id": p2.id, "quantity": 160}])
    assert r.status_code == 201, r.json()
    [order] = r.json()["data"]
    assert order["created"] is True and order["status"] == "DRAFT" and order["supplier_id"] == world["a_supplier"].id
    assert order["due_date"] == (TODAY + timedelta(days=5)).isoformat()  # 오늘 + 리드타임 5일
    lines = {i["product_sku"]: i for i in order["items"]}
    assert (lines["S9-1"]["quantity"], lines["S9-2"]["quantity"]) == (150, 160)  # 사용자가 보낸 수량 그대로
    assert lines["S9-1"]["recommended_quantity"] == lines["S9-2"]["recommended_quantity"] == 160  # 10 × 19 + 20 − 50
    assert lines["S9-1"]["unit_price"] == 1000  # 품목 단가
    assert lines["S9-1"]["recommendation_reason"].endswith("추천 수량은 160개입니다.")
    assert drafts(session, world) == 1


def test_s10_existing_draft_gets_items_added(client, world, session):
    """S10: 같은 공급업체 DRAFT 가 이미 있으면 새로 만들지 않고 품목만 추가 (두 번째는 created: false, 같은 발주서)."""
    p1 = stock_50_sold_300(session, world, "S10-1")
    p2 = stock_50_sold_300(session, world, "S10-2")
    session.commit()
    first = post(client, [{"product_id": p1.id, "quantity": 160}]).json()["data"][0]
    second = post(client, [{"product_id": p2.id, "quantity": 160}]).json()["data"][0]
    assert first["created"] is True and second["created"] is False
    assert second["id"] == first["id"] and second["po_number"] == first["po_number"]
    assert [i["product_sku"] for i in second["items"]] == ["S10-1", "S10-2"]
    assert drafts(session, world) == 1


# ----- 묶기·수량 -----

def test_groups_by_supplier_with_hand_calculated_quantities(client, world, session):
    """업체 2곳 품목이 섞이면 업체마다 1장. A업체(리드타임 5): 160. C업체(리드타임 10): 재주문점 10 × 10 + 20 = 120, 추천 10 × 24 + 20 − 50 = 210."""
    c = Supplier(company_id=world["a_company"].id, name="C업체", lead_time_days=10)
    session.add(c)
    session.flush()
    a1 = stock_50_sold_300(session, world, "A-1")
    c1 = stock_50_sold_300(session, world, "C-1", supplier=c)
    a2 = stock_50_sold_300(session, world, "A-2")
    session.commit()
    r = post(client, [{"product_id": p.id, "quantity": 100} for p in (a1, c1, a2)])
    assert r.status_code == 201, r.json()
    by_supplier = {o["supplier_name"]: o for o in r.json()["data"]}
    assert set(by_supplier) == {"A업체", "C업체"} and all(o["created"] for o in by_supplier.values())
    assert {i["product_sku"]: i["recommended_quantity"] for i in by_supplier["A업체"]["items"]} == {"A-1": 160, "A-2": 160}
    assert [(i["product_sku"], i["recommended_quantity"]) for i in by_supplier["C업체"]["items"]] == [("C-1", 210)]
    assert by_supplier["C업체"]["due_date"] == (TODAY + timedelta(days=10)).isoformat()
    assert drafts(session, world) == 2


def test_s4_cancelled_order_still_recommended(client, world, session):
    """S4: CANCELLED 160 은 진행 중이 아니다 → 추천 160 으로 초안이 만들어진다."""
    p = stock_50_sold_300(session, world, "S4")
    add_po(session, world, "PO-X", "CANCELLED", p, 160)
    session.commit()
    r = post(client, [{"product_id": p.id, "quantity": 160}])
    assert r.status_code == 201 and r.json()["data"][0]["items"][0]["recommended_quantity"] == 160


# ----- 두 번 보내기·막히는 경우 (아무것도 만들어지지 않는다) -----

def test_same_request_twice_second_is_duplicate_item(client, world, session):
    """더블클릭·재시도: 같은 요청을 두 번 보내면 두 번째는 409 DUPLICATE_ITEM, 발주서 1장·줄 1개 그대로."""
    p = stock_50_sold_300(session, world, "TWICE")
    session.commit()
    body = [{"product_id": p.id, "quantity": 160}]
    first = post(client, body)
    second = post(client, body)
    assert first.status_code == 201
    assert second.status_code == 409 and second.json()["error"]["code"] == "DUPLICATE_ITEM"
    assert second.json()["error"]["details"]["po_number"] == first.json()["data"][0]["po_number"]
    assert drafts(session, world) == 1
    assert session.scalar(select(func.count()).select_from(PurchaseOrderItem).where(PurchaseOrderItem.product_id == p.id)) == 1


def test_not_recommended_items_rejected(client, world, session):
    """추천 대상이 아닌 품목이 하나라도 있으면 409 NOT_RECOMMENDED, 초안은 하나도 만들지 않는다(사용자 결정).

    S3(ORDERED 160 이 오는 중 → 가용재고 210 > 70) → ENOUGH_STOCK, 첫 입출고 13일 전 → INSUFFICIENT_DATA, 판매 없음 → NO_SALES_30D.
    """
    ok = stock_50_sold_300(session, world, "OK")
    s3 = stock_50_sold_300(session, world, "S3")
    add_po(session, world, "PO-1", "ORDERED", s3, 160)
    new = add_product(session, world, "NEW")
    add_move(session, world, new, "RECEIPT", "IN", 350, 13)
    add_move(session, world, new, "SALE", "OUT", 300, 1)
    idle = add_product(session, world, "IDLE")
    add_move(session, world, idle, "RECEIPT", "IN", 50, 40)
    session.commit()
    r = post(client, [{"product_id": p.id, "quantity": 10} for p in (ok, s3, new, idle)])
    assert r.status_code == 409 and r.json()["error"]["code"] == "NOT_RECOMMENDED"
    assert {d["sku"]: d["reason"] for d in r.json()["error"]["details"]} == {
        "S3": "ENOUGH_STOCK", "NEW": "INSUFFICIENT_DATA", "IDLE": "NO_SALES_30D"}
    assert drafts(session, world) == 0


def test_inactive_product_and_supplier_rejected(client, world, session):
    """비활성 품목, 기본 공급업체가 비활성인 품목 → 409 INACTIVE_REFERENCE."""
    off_product = stock_50_sold_300(session, world, "OFF", is_active=False)
    off_supplier = Supplier(company_id=world["a_company"].id, name="꺼진업체", lead_time_days=5, is_active=False)
    session.add(off_supplier)
    session.flush()
    orphan = stock_50_sold_300(session, world, "ORPHAN", supplier=off_supplier)
    session.commit()
    for p in (off_product, orphan):
        r = post(client, [{"product_id": p.id, "quantity": 10}])
        assert r.status_code == 409 and r.json()["error"]["code"] == "INACTIVE_REFERENCE", r.json()
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0


def test_other_company_product_is_404(client, world, session):
    """다른 회사 품목 번호 → 404 (회사 B 에는 아무것도 생기지 않는다)."""
    b = stock_50_sold_300(session, world, "B-1", key="b")
    session.commit()
    r = post(client, [{"product_id": b.id, "quantity": 10}])
    assert r.status_code == 404 and r.json()["error"]["details"] == [{"field": "items", "reason": "not_found"}]
    assert session.scalar(select(func.count()).select_from(PurchaseOrder)) == 0


def test_request_validation(client, world, session):
    """같은 품목 두 줄 409 DUPLICATE_ITEM. 빈 목록·101개·추천 수량을 보내면·수량 0 은 422."""
    p = stock_50_sold_300(session, world, "V")
    session.commit()
    line = {"product_id": p.id, "quantity": 10}
    assert post(client, [line, line]).json()["error"]["code"] == "DUPLICATE_ITEM"
    assert post(client, []).status_code == 422
    assert post(client, [line] * 101).status_code == 422
    assert post(client, [{**line, "recommended_quantity": 999}]).status_code == 422  # 추천 수량은 서버만 정한다
    assert post(client, [{"product_id": p.id, "quantity": 0}]).status_code == 422
    assert drafts(session, world) == 0


def test_requires_login(client, world):
    """로그인 없이는 401."""
    assert client.post(URL, json={"items": [{"product_id": 1, "quantity": 1}]}).status_code == 401


# ----- 진짜 commit 하는 테스트: 동시 요청, 중간 실패 -----

def committed_products(engine, data, count, supplier_id=None):
    """committed_company 에 추천 대상 품목 count 개를 commit (40일 전 입고 300, 어제 판매 300 → 현재고 0, 일평균 10).

    committed_company 업체는 리드타임 3, 안전재고 0 → 재주문점 30, 추천 10 × 17 + 0 − 0 = 170.
    """
    def create(s):
        supplier = supplier_id or s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"]))
        ids = []
        for k in range(count):
            p = Product(company_id=data["company_id"], sku=f"R-{supplier}-{k}", name="품목", unit="개", unit_cost=500,
                        default_supplier_id=supplier)
            s.add(p)
            s.flush()
            for mtype, direction, day in (("RECEIPT", "IN", 40), ("SALE", "OUT", 1)):
                s.add(InventoryMovement(company_id=data["company_id"], product_id=p.id, created_by=data["admin_id"],
                                        movement_type=mtype, direction=direction, quantity=300,
                                        movement_date=TODAY - timedelta(days=day),
                                        sales_channel="OWN_MALL" if mtype == "SALE" else None))
            ids.append(p.id)
        return ids

    return run_in_new_session(engine, create)


def draft_call(engine, data, product_ids):
    """초안 만들기 한 건을 새 연결로 (API 요청 하나와 같은 모양) → [(발주서 id, created)]."""
    request = DraftCreate(items=[{"product_id": p, "quantity": 170} for p in product_ids])
    return lambda: run_in_new_session(engine, lambda s: [
        (o.id, created) for o, created in recommendation_service.create_drafts(data["company_id"], s, data["admin_id"], TODAY, request)])


def lines_of(engine, data):
    """회사의 DRAFT 발주서 id 목록과 줄의 품목 id 목록."""
    def read(s):
        orders = list(s.scalars(select(PurchaseOrder.id).where(
            PurchaseOrder.company_id == data["company_id"], PurchaseOrder.status == "DRAFT")))
        items = list(s.scalars(select(PurchaseOrderItem.product_id).where(PurchaseOrderItem.company_id == data["company_id"])))
        return orders, items
    return run_in_new_session(engine, read)


def test_concurrent_drafts_different_items_one_draft(engine, committed_company):
    """같은 업체에 서로 다른 품목 8건을 동시에 → 모두 성공, DRAFT 1장에 8줄, created: true 는 1건 (회사 행 잠금)."""
    data = committed_company
    ids = committed_products(engine, data, 8)
    gate = hold_row_lock(engine, Company, data["company_id"])  # 회사 줄을 0.5초 잠가 8건이 확실히 겹치게
    results = run_at_once(gate, *[delayed(draft_call(engine, data, [p])) for p in ids])[1:]  # 문지기 결과는 빼고
    assert not [r for r in results if isinstance(r, Exception)], results
    assert sum(created for [(_, created)] in results) == 1
    orders, items = lines_of(engine, data)
    assert len(orders) == 1 and sorted(items) == sorted(ids)


def test_concurrent_same_item_once(engine, committed_company):
    """같은 품목 8건을 동시에 → 1건만 성공, 7건은 409 DUPLICATE_ITEM, DRAFT 1장에 1줄."""
    data = committed_company
    [pid] = committed_products(engine, data, 1)
    gate = hold_row_lock(engine, Company, data["company_id"])
    results = run_at_once(gate, *[delayed(draft_call(engine, data, [pid])) for _ in range(8)])[1:]
    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 7 and all(isinstance(e, AppError) and e.code == "DUPLICATE_ITEM" for e in failures), failures
    orders, items = lines_of(engine, data)
    assert len(orders) == 1 and items == [pid]


def test_failure_in_second_supplier_rolls_back_first(engine, committed_company):
    """업체 2곳 요청에서 첫 업체 초안을 만든 뒤 둘째 업체에서 409 가 나면, 첫 업체 초안도 저장되지 않는다(별도 연결로 확인)."""
    data = committed_company
    [first] = committed_products(engine, data, 1)  # 기본 업체(번호가 작다) → 먼저 처리되어 새 초안이 만들어진다
    def add_supplier(s):
        supplier = Supplier(company_id=data["company_id"], name="둘째업체", lead_time_days=3)
        s.add(supplier)
        s.flush()  # id 받기
        return supplier.id

    second_supplier = run_in_new_session(engine, add_supplier)  # 번호가 더 크다 → 나중에 처리
    [second] = committed_products(engine, data, 1, supplier_id=second_supplier)
    draft_call(engine, data, [second])()  # 둘째 업체에 이 품목이 든 DRAFT 를 미리 만든다
    before = lines_of(engine, data)
    try:
        draft_call(engine, data, [first, second])()  # 첫 업체 초안 생성 → 둘째 업체에서 DUPLICATE_ITEM
        raise AssertionError("409 가 나야 한다")
    except AppError as e:
        assert e.code == "DUPLICATE_ITEM"
    assert lines_of(engine, data) == before  # 첫 업체 초안·줄이 남지 않았다
