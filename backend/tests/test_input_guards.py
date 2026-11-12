"""입력 검증 공통 규칙(#190) 테스트: 멱등 키, 날짜 하한 5년, 큰 수량·비활성 품목 확인 경고(409 CONFIRM_REQUIRED)."""

import json  # 저장된 응답 본문 읽기, 가져오기 options
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from fastapi.responses import JSONResponse  # 멱등 키 재요청의 응답 모양
from sqlalchemy import func, select, text, update  # 개수 세기, 시각 당기기
from sqlalchemy.orm import Session  # 동시성 테스트 결과 확인용 새 세션

from app.clock import oldest_allowed, seoul_today  # 날짜 하한, 서울 기준 오늘
from app.models import IdempotencyKey, InventoryMovement, Product  # 표
from app.schemas.movements import MovementCreate  # 입출고 요청 모양 (동시성 테스트)
from app.services import idempotency  # 멱등 키 처리
from app.services import stock as stock_service  # 재고 계산·이력 쓰기
from tests.concurrency import delayed, hold_row_lock, run_at_once, run_in_new_session
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/inventory-movements"  # 직접 입출고 경로
PO_URL = "/api/v1/purchase-orders"  # 발주 경로
TODAY = seoul_today()


@pytest.fixture
def goods(world, session):
    """회사 A 품목: SOLD(40일 전 입고 1000, 5일 전 판매 100 → 30일 판매 100, 경고 한도 300, 현재고 900),
    QUIET(입고 1000, 판매 없음 → 큰 수량 검사 안 함). 회사 B 품목 B-1(입고 100)."""
    a, b = world["a_company"], world["b_company"]
    out = {}
    for key, company, supplier, user in (("SOLD", a, world["a_supplier"], world["a_admin"]),
                                         ("QUIET", a, world["a_supplier"], world["a_admin"]),
                                         ("B-1", b, world["b_supplier"], world["b_admin"])):
        p = Product(company_id=company.id, sku=key, name=f"품목{key}", unit="개", unit_cost=1000, default_supplier_id=supplier.id)
        session.add(p)
        session.flush()
        stock_service.register_movement(company.id, session, user.id, product_id=p.id, movement_type="RECEIPT", direction="IN",
                                        quantity=1000 if company is a else 100, movement_date=TODAY - timedelta(days=40))
        out[key] = p
    stock_service.register_movement(a.id, session, world["a_admin"].id, product_id=out["SOLD"].id, movement_type="SALE",
                                    direction="OUT", quantity=100, movement_date=TODAY - timedelta(days=5), sales_channel="OWN_MALL")
    session.commit()
    return out


def post(client, product, key=None, **fields):
    """직접 입출고 (기본: 입고 1개). key 가 있으면 Idempotency-Key 헤더로 보낸다."""
    body = {"product_id": product.id, "movement_type": "RECEIPT", "quantity": 1, **fields}
    return client.post(URL, json=body, headers={"Idempotency-Key": key} if key is not None else {})


def count(session, product):
    return session.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.product_id == product.id))


def stock(session, product):
    return stock_service.current_stock(product.company_id, session, product.id)


def ordered_po(client, world, product, quantity):
    """회사 A 의 ORDERED 발주서 (관리자로 작성 → 승인 → 발주) → (발주서 id, 줄 id). 끝나면 담당자로 돌아온다."""
    login_as(client, "admin@a.test")
    order = client.post(PO_URL, json={"supplier_id": world["a_supplier"].id,
                                      "items": [{"product_id": product.id, "quantity": quantity, "unit_price": 800}]}).json()["data"]
    assert client.post(f"{PO_URL}/{order['id']}/approve").status_code == 200
    assert client.post(f"{PO_URL}/{order['id']}/order").status_code == 200
    login_as(client)
    return order["id"], order["items"][0]["id"]


def receive(client, order_id, line_id, quantity, key=None, **fields):
    return client.post(f"{PO_URL}/{order_id}/receipts", json={"items": [{"purchase_order_item_id": line_id, "quantity": quantity}], **fields},
                       headers={"Idempotency-Key": key} if key is not None else {})


# ----- 멱등 키 -----
def test_same_key_twice_saves_once(client, world, goods, session):
    """같은 키로 두 번 보내면 이력 1건, 두 번째 응답은 첫 응답과 상태 코드까지 같다. 헤더가 없으면 지금처럼 2건."""
    login_as(client)
    p = goods["QUIET"]
    first, second = post(client, p, "k-1", quantity=7), post(client, p, "k-1", quantity=7)
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert count(session, p) == 2 and stock(session, p) == 1007  # 준비 입고 1 + 이번 1
    assert post(client, p, quantity=7).status_code == 201 and post(client, p, quantity=7).status_code == 201
    assert count(session, p) == 4  # 키 없으면 두 번 다 저장 (기존 동작)


def test_po_receipt_same_key_adds_stock_once(client, world, goods, session):
    """완료 기준: 발주 100 에 입고 30 을 같은 키로 두 번 보내도 재고는 30 만 늘고 누적 입고량도 30."""
    order_id, line_id = ordered_po(client, world, goods["QUIET"], 100)
    first = receive(client, order_id, line_id, 30, "rcv-1")
    second = receive(client, order_id, line_id, 30, "rcv-1")
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert first.json()["data"]["items"][0]["received_quantity"] == 30
    assert stock(session, goods["QUIET"]) == 1030


def test_correction_same_key_once(client, world, goods, session):
    """정정도 같은 키 두 번 = 정정 1건."""
    login_as(client)
    sale = post(client, goods["QUIET"], movement_type="SALE", quantity=10, sales_channel="OWN_MALL").json()["data"]
    send = lambda: client.post(f"{URL}/{sale['id']}/corrections", json={"quantity": 4, "reason": "오입력"},
                               headers={"Idempotency-Key": "fix-1"})
    assert send().json() == send().json()
    assert stock(session, goods["QUIET"]) == 994  # 1000 − 10 + 4 (정정 한 번만)


def test_same_key_different_body_is_422(client, world, goods, session):
    login_as(client)
    p = goods["QUIET"]
    assert post(client, p, "k-2", quantity=5).status_code == 201
    r = post(client, p, "k-2", quantity=6)
    assert r.status_code == 422 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    assert stock(session, p) == 1005


def test_keys_are_per_company_and_per_endpoint(client, world, goods, session):
    """다른 회사의 같은 키, 같은 회사의 다른 경로의 같은 키는 서로 영향이 없다."""
    login_as(client)
    sale = post(client, goods["QUIET"], "shared", movement_type="SALE", quantity=10, sales_channel="OWN_MALL")
    assert sale.status_code == 201
    fix = client.post(f"{URL}/{sale.json()['data']['id']}/corrections", json={"quantity": 1, "reason": "오입력"},
                      headers={"Idempotency-Key": "shared"})
    assert fix.status_code == 201  # 다른 경로라 다른 키
    login_as(client, "staff@b.test")
    other = post(client, goods["B-1"], "shared", movement_type="SALE", quantity=10, sales_channel="OWN_MALL")
    assert other.status_code == 201 and other.json()["data"]["product_id"] == goods["B-1"].id  # 회사 A 응답이 아니라 새로 처리
    assert stock(session, goods["B-1"]) == 90


def test_expired_key_is_processed_again(client, world, goods, session):
    """24시간이 지난 키는 지우고 새 요청으로 처리한다."""
    login_as(client)
    p = goods["QUIET"]
    assert post(client, p, "old", quantity=3).status_code == 201
    session.execute(update(IdempotencyKey).values(created_at=text("now() - interval '25 hours'")))  # 25시간 전으로 당긴다
    session.commit()
    assert post(client, p, "old", quantity=3).status_code == 201
    assert stock(session, p) == 1006  # 두 번 다 반영
    assert session.scalar(select(func.count()).select_from(IdempotencyKey)) == 1  # 만료 행은 지워지고 새 행 하나


def test_failed_request_does_not_keep_key(client, world, goods, session):
    """4xx 로 끝난 요청은 키를 남기지 않는다: 고친 내용으로 같은 키를 다시 보내면 처리된다."""
    login_as(client)
    p = goods["QUIET"]
    r = post(client, p, "retry", movement_type="SALE", quantity=5000, sales_channel="OWN_MALL")
    assert r.status_code == 409 and r.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert post(client, p, "retry", movement_type="SALE", quantity=50, sales_channel="OWN_MALL").status_code == 201
    assert stock(session, p) == 950


def test_confirm_flow_with_same_key(client, world, goods, session):
    """409 확인 → confirm_warnings: true 로 같은 키 재전송 → 201 → 같은 키로 또 보내면 첫 201 응답 그대로 (확인 칸은 지문에서 뺀다)."""
    login_as(client)
    p = goods["SOLD"]
    warned = post(client, p, "big", quantity=500)
    assert warned.status_code == 409 and warned.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert session.scalar(select(func.count()).select_from(IdempotencyKey)) == 0  # 409 는 키를 남기지 않는다
    done = post(client, p, "big", quantity=500, confirm_warnings=True)
    assert done.status_code == 201
    again = post(client, p, "big", quantity=500, confirm_warnings=True)
    assert again.status_code == 201 and again.json() == done.json()
    assert post(client, p, "big", quantity=500).json() == done.json()  # 확인 칸이 없어도 같은 요청
    assert stock(session, p) == 1400  # 900 + 500 한 번만


@pytest.mark.parametrize("key", ["", "x" * 101])
def test_bad_key_header_is_422(client, world, goods, key):
    login_as(client)
    assert post(client, goods["QUIET"], key).status_code == 422


def test_concurrent_same_key_saves_once(engine, committed_company):
    """같은 회사·키의 요청 두 건이 동시에: 이력 1건, 둘 다 같은 201 응답. 두 번째는 첫 요청이 끝날 때까지 키에서 기다린다."""
    data = committed_company
    body = MovementCreate(product_id=data["product_id"], movement_type="RECEIPT", quantity=5)

    def request(s):
        def work():
            movement, after = stock_service.create_movement(data["company_id"], s, data["admin_id"], body)
            return {"data": {"id": movement.id, "stock_after": after}}
        return idempotency.run(s, data["company_id"], URL, "same-key", body, work)

    gate = hold_row_lock(engine, Product, data["product_id"])  # 품목을 잠가 두 요청이 겹치게 한다
    _, a, b = run_at_once(gate, delayed(lambda: run_in_new_session(engine, request)),
                          delayed(lambda: run_in_new_session(engine, request)))
    bodies = [json.loads(r.body) if isinstance(r, JSONResponse) else r for r in (a, b)]
    assert not any(isinstance(r, Exception) for r in (a, b)), (a, b)
    assert bodies[0] == bodies[1]  # 두 번째는 첫 응답 그대로
    assert sum(isinstance(r, JSONResponse) for r in (a, b)) == 1  # 하나는 처리, 하나는 저장된 응답
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(InventoryMovement).where(
            InventoryMovement.product_id == data["product_id"])) == 1


# ----- 날짜 하한 5년 -----
def test_date_floor_direct_and_po_receipt(client, world, goods):
    """오늘로부터 5년 전 날짜는 통과, 그 하루 전은 422 (직접 입출고·발주 입고)."""
    floor = oldest_allowed(TODAY)
    login_as(client)
    p = goods["QUIET"]
    assert post(client, p, movement_date=floor.isoformat()).status_code == 201
    r = post(client, p, movement_date=(floor - timedelta(days=1)).isoformat())
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "movement_date"
    order_id, line_id = ordered_po(client, world, p, 100)
    assert receive(client, order_id, line_id, 1, movement_date=(floor - timedelta(days=1)).isoformat()).status_code == 422
    assert receive(client, order_id, line_id, 1, movement_date=floor.isoformat()).status_code == 201


def test_date_floor_imports(client, world, goods):
    """판매·입고 가져오기는 5년보다 이른 날짜 행을 TOO_OLD_DATE 문제 행으로 표시한다."""
    login_as(client)
    floor, old = oldest_allowed(TODAY).isoformat(), (oldest_allowed(TODAY) - timedelta(days=1)).isoformat()
    sales = ("주문번호,주문일시,상품코드,수량\n" f"S1,{old},QUIET,1\nS2,{floor},QUIET,1\n").encode("utf-8-sig")
    r = client.post("/api/v1/sales-imports/preview", files={"file": ("o.csv", sales)}, data={"options": json.dumps(
        {"ref_col": 0, "date_col": 1, "product_col": 2, "quantity_col": 3, "sales_channel": "OWN_MALL"})}).json()["data"]
    assert [x["reason"] for x in r["problems"]] == ["TOO_OLD_DATE"] and r["apply_count"] == 1
    receipts = ("입고일,상품코드,수량\n" f"{old},QUIET,1\n{floor},QUIET,2\n").encode("utf-8-sig")
    r = client.post("/api/v1/receipt-imports/preview", files={"file": ("in.csv", receipts)}, data={"options": json.dumps(
        {"date_col": 0, "product_col": 1, "quantity_col": 2})}).json()["data"]
    assert [x["reason"] for x in r["problems"]] == ["TOO_OLD_DATE"] and r["apply_count"] == 1


# ----- 큰 수량 경고: 30일 판매 100 → 300 까지 통과, 301 부터 확인 -----
@pytest.mark.parametrize("fields", [
    {"movement_type": "RECEIPT"},
    {"movement_type": "SALE", "sales_channel": "OWN_MALL"},
    {"movement_type": "DISPOSAL"},
    {"movement_type": "ADJUSTMENT", "direction": "OUT", "reason": "실사 차이"},
], ids=["receipt", "sale", "disposal", "adjust"])
def test_large_quantity_needs_confirm(client, world, goods, session, fields):
    login_as(client)
    p = goods["SOLD"]
    r = post(client, p, quantity=301, **fields)
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFIRM_REQUIRED"
    assert r.json()["error"]["details"]["warnings"] == [
        {"code": "LARGE_QUANTITY", "product_id": p.id, "sku": "SOLD", "quantity": 301, "sales_30d": 100, "limit": 300}]
    assert count(session, p) == 2  # 아무것도 저장하지 않았다
    assert post(client, p, quantity=301, confirm_warnings=True, **fields).status_code == 201
    assert post(client, p, quantity=300, **fields).status_code == 201  # 한도까지는 경고 없음


def test_large_quantity_po_receipt(client, world, goods, session):
    order_id, line_id = ordered_po(client, world, goods["SOLD"], 400)
    r = receive(client, order_id, line_id, 301)
    assert r.status_code == 409 and r.json()["error"]["details"]["warnings"][0]["code"] == "LARGE_QUANTITY"
    assert stock(session, goods["SOLD"]) == 900  # 저장 안 됨
    assert receive(client, order_id, line_id, 301, confirm_warnings=True).status_code == 201


def test_no_warning_without_sales_or_for_correction(client, world, goods):
    """30일 판매가 0 인 품목은 큰 수량을 검사하지 않는다. 정정도 검사하지 않는다(원래 수량 이하로 이미 묶여 있다)."""
    login_as(client)
    assert post(client, goods["QUIET"], quantity=100000).status_code == 201
    big = post(client, goods["SOLD"], quantity=500, confirm_warnings=True).json()["data"]
    assert client.post(f"{URL}/{big['id']}/corrections", json={"quantity": 400, "reason": "오입력"}).status_code == 201


# ----- 비활성 품목 경고 -----
def test_inactive_product_needs_confirm_on_direct_movement(client, world, goods, session):
    login_as(client)
    p = goods["QUIET"]
    client.patch(f"/api/v1/products/{p.id}", json={"is_active": False})
    r = post(client, p, movement_type="SALE", quantity=1, sales_channel="OWN_MALL")
    assert r.status_code == 409 and r.json()["error"]["details"]["warnings"] == [
        {"code": "INACTIVE_PRODUCT", "product_id": p.id, "sku": "QUIET"}]
    assert post(client, p, movement_type="SALE", quantity=1, sales_channel="OWN_MALL", confirm_warnings=True).status_code == 201


def test_inactive_product_po_receipt_has_no_warning(client, world, goods, session):
    """이미 ORDERED 인 발주의 입고는 비활성 품목이어도 경고 없이 된다 (데이터 원칙 8)."""
    order_id, line_id = ordered_po(client, world, goods["QUIET"], 10)
    session.get(Product, goods["QUIET"].id).is_active = False
    session.commit()
    assert receive(client, order_id, line_id, 10).status_code == 201
