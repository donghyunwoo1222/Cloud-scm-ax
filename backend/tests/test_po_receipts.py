"""발주 입고 API (#35) 테스트: POST /purchase-orders/{id}/receipts 와 입고 정정. 동시 입고·교착은 test_concurrency.py."""

from datetime import timedelta  # 날짜 빼기
from types import SimpleNamespace  # 로그인 사용자 대신 넣을 간단한 값 묶음

import pytest  # 테스트 도구
from fastapi.testclient import TestClient  # 진짜 DB 세션을 쓰는 별도 클라이언트
from sqlalchemy import func, select  # 개수 세기
from sqlalchemy.orm import Session  # 요청마다 새 세션

from app.auth.deps import get_current_user  # 로그인 사용자 의존성
from app.clock import seoul_today  # 서울 기준 오늘
from app.db import get_db  # 앱이 쓰는 DB 세션 의존성
from app.main import app  # 테스트할 앱
from app.models import InventoryMovement, Product, PurchaseOrder, Supplier  # 표
from app.services import (
    purchase_orders as po_service,  # 발주 입고 service (저장 함수를 바꿔 끼울 곳)
)
from tests.concurrency import (  # ORDERED 발주 만들기, 진짜 commit 하는 새 세션 (committed_company 는 conftest)
    ordered_po,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/purchase-orders"  # 발주 경로


@pytest.fixture
def po(client, world, session):
    """회사 A 의 ORDERED 발주서: P1 100개, P2 50개, P3 10개 (API 로 작성 → 승인 → 발주) → 응답 data."""
    products = []
    for sku in ("P1", "P2", "P3"):
        p = Product(company_id=world["a_company"].id, sku=sku, name=f"품목{sku}", unit="개", unit_cost=1000,
                    default_supplier_id=world["a_supplier"].id)
        session.add(p)
        products.append(p)
    session.commit()
    login_as(client, "admin@a.test")
    lines = [{"product_id": p.id, "quantity": q, "unit_price": 800} for p, q in zip(products, (100, 50, 10))]
    order = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": lines}).json()["data"]
    assert client.post(f"{URL}/{order['id']}/approve").status_code == 200
    data = client.post(f"{URL}/{order['id']}/order").json()["data"]
    assert data["status"] == "ORDERED"
    login_as(client)  # 입고는 담당자로
    return data


def item(po, sku):
    """SKU 로 발주 줄 찾기."""
    return next(i for i in po["items"] if i["product_sku"] == sku)


def receive(client, po, *lines, **fields):
    """입고 요청. lines 는 (SKU, 수량)."""
    return client.post(f"{URL}/{po['id']}/receipts", json={
        "items": [{"purchase_order_item_id": item(po, sku)["id"], "quantity": q} for sku, q in lines], **fields})


def stock(client, po, sku):
    return client.get(f"/api/v1/stock/{item(po, sku)['product_id']}").json()["data"]["current_stock"]  # 현재고


def received(response, sku):
    return next(i for i in response.json()["data"]["items"] if i["product_sku"] == sku)["received_quantity"]  # 누적 입고량


# ----- 완료 기준 1: 부분이면 ORDERED, 전량이면 RECEIVED -----
def test_partial_then_full_receipt(client, world, po):
    r = receive(client, po, ("P1", 40), ("P2", 50))
    assert r.status_code == 201 and r.json()["data"]["status"] == "ORDERED"  # P1 40/100 이라 부분
    assert received(r, "P1") == 40 and received(r, "P2") == 50 and r.json()["data"]["received_at"] is None
    assert stock(client, po, "P1") == 40 and stock(client, po, "P2") == 50  # 재고가 입고만큼 늘었다
    r = receive(client, po, ("P1", 60), ("P3", 10))
    d = r.json()["data"]
    assert d["status"] == "RECEIVED" and received(r, "P1") == 100
    assert d["received_at"] == f"{seoul_today() - timedelta(days=1)}T15:00:00Z"  # 입고일(오늘)의 서울 자정 = UTC 로 전날 15시
    rows = client.get("/api/v1/inventory-movements", params={"movement_type": "RECEIPT"}).json()["data"]
    assert all(m["purchase_order_item_id"] is not None for m in rows) and len(rows) == 4  # 줄마다 RECEIPT 이력, 발주 줄과 연결


def test_received_at_is_latest_receipt_date(client, world, po):
    """received_at = 이 발주서 입고 이력 중 가장 늦은 입고일 (RECEIVED 가 된 요청의 날짜가 아니다)."""
    today = seoul_today()
    receive(client, po, ("P1", 100), movement_date=today.isoformat())  # 먼저 오늘 날짜로
    r = receive(client, po, ("P2", 50), ("P3", 10), movement_date=(today - timedelta(days=3)).isoformat())  # 마지막 요청은 3일 전 날짜
    d = r.json()["data"]
    assert d["status"] == "RECEIVED"
    assert d["received_at"] == f"{today - timedelta(days=1)}T15:00:00Z"  # 가장 늦은 입고일 = 오늘, 서울 자정 = UTC 전날 15시


# ----- 완료 기준 2: OVER_RECEIPT -----
def test_over_receipt_message_has_remaining(client, world, po):
    receive(client, po, ("P1", 70))
    r = receive(client, po, ("P1", 40))
    err = r.json()["error"]
    assert r.status_code == 409 and err["code"] == "OVER_RECEIPT"
    assert "30개까지만" in err["message"] and err["details"]["remaining"] == 30


def test_failure_on_second_line_saves_nothing(client, world, po, session):
    """품목 3개 중 2번째가 초과면 1번째도 저장되지 않는다 (재고·이력·상태 모두 그대로)."""
    r = receive(client, po, ("P1", 10), ("P2", 51), ("P3", 5))
    assert r.status_code == 409 and r.json()["error"]["code"] == "OVER_RECEIPT"
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == 0
    assert stock(client, po, "P1") == 0
    assert client.get(f"{URL}/{po['id']}").json()["data"]["status"] == "ORDERED"


def test_error_while_saving_second_line_rolls_back_first(engine, committed_company, monkeypatch):
    """#71 C: 첫 줄을 저장(flush)한 뒤 둘째 줄 저장 중 예외가 나면, 다른 연결에서 봐도 첫 줄이 없다.

    위 테스트는 쓰기 전 검사(OVER_RECEIPT)에서 끝나 '반쯤 저장'을 확인하지 못한다. 여기서는 진짜 DB 연결을 쓰는
    실제 API 경로로 보내고, 둘째 줄의 register_movement 에서 강제로 예외를 낸다.
    """
    data = committed_company
    def add_product(s):
        p = Product(company_id=data["company_id"], sku="CC-R2", name="입고둘째", unit="개", unit_cost=1000,
                    default_supplier_id=s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
        s.add(p)
        s.flush()  # id 받기
        return p.id

    order_id, lines = ordered_po(engine, data, [data["product_id"], run_in_new_session(engine, add_product)])  # 2줄 ORDERED 발주
    real_register = po_service.register_movement  # 원래 저장 함수
    calls = []  # 저장 시도 횟수

    def fail_on_second(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:  # 둘째 줄 저장 단계
            raise RuntimeError("둘째 줄 저장 중 강제 오류")
        return real_register(*args, **kwargs)  # 첫 줄은 실제로 저장(flush)

    monkeypatch.setattr(po_service, "register_movement", fail_on_second)

    def real_db():  # 앱의 get_db 와 같은 모양: 요청마다 새 세션, 끝나면 닫기 (테스트 DB 로)
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = real_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(  # 로그인 대신 이 회사 관리자로
        id=data["admin_id"], company_id=data["company_id"], role="ADMIN", is_active=True)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:  # 500 을 예외 대신 응답으로 받는다
            r = c.post(f"{URL}/{order_id}/receipts", json={
                "items": [{"purchase_order_item_id": i, "quantity": 10} for i in lines]})
    finally:
        app.dependency_overrides.clear()  # 다른 테스트에 영향 없게
    assert r.status_code == 500 and len(calls) == 2  # 첫 줄은 저장까지 갔고 둘째 줄에서 실패했다
    saved = run_in_new_session(engine, lambda s: s.scalar(select(func.count()).select_from(InventoryMovement).where(
        InventoryMovement.company_id == data["company_id"])))
    assert saved == 0  # 별도 연결에서 봐도 첫 줄 이력이 없다 (요청 전체가 취소됨)
    status = run_in_new_session(engine, lambda s: s.get(PurchaseOrder, order_id).status)
    assert status == "ORDERED"  # 상태도 그대로


def test_validation(client, world, po):
    assert receive(client, po).status_code == 422  # 줄 0개
    assert receive(client, po, ("P1", 0)).status_code == 422  # 수량 1 미만
    assert receive(client, po, ("P1", 1), ("P1", 2)).status_code == 422  # 같은 줄 두 번
    future = (seoul_today() + timedelta(days=1)).isoformat()
    assert receive(client, po, ("P1", 1), movement_date=future).status_code == 422  # 미래 입고일
    r = client.post(f"{URL}/{po['id']}/receipts", json={"items": [{"purchase_order_item_id": 999999, "quantity": 1}]})
    assert r.status_code == 404  # 이 발주서에 없는 줄


# ----- ORDERED 가 아니면 409 -----
@pytest.mark.parametrize("status", ["DRAFT", "APPROVED", "RECEIVED", "CANCELLED"])
def test_only_ordered_can_receive(client, world, po, session, status):
    session.get(PurchaseOrder, po["id"]).status = status
    session.commit()
    r = receive(client, po, ("P1", 1))
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATUS"


def test_inactive_product_can_still_be_received(client, world, po, session):
    """품목이 비활성이 되어도 이미 ORDERED 인 발주의 입고는 된다."""
    session.get(Product, item(po, "P1")["product_id"]).is_active = False
    session.commit()
    assert receive(client, po, ("P1", 5)).status_code == 201


def test_cancel_blocked_after_real_receipt(client, world, po):
    receive(client, po, ("P1", 5))
    r = client.post(f"{URL}/{po['id']}/cancel")
    assert r.status_code == 409 and r.json()["error"]["code"] == "CANNOT_CANCEL_RECEIVED"


# ----- 완료 기준 3: 입고 정정은 ORDERED 일 때만 (실제 입고 API 로 만든 이력) -----
def test_receipt_correction_with_real_receipt(client, world, po):
    receive(client, po, ("P1", 70))
    receipt_id = client.get("/api/v1/inventory-movements", params={"movement_type": "RECEIPT"}).json()["data"][0]["id"]
    r = client.post(f"/api/v1/inventory-movements/{receipt_id}/corrections", json={"quantity": 20, "reason": "70을 50으로"})
    assert r.status_code == 201 and r.json()["data"]["purchase_order_item_id"] == item(po, "P1")["id"]  # 같은 발주 줄에 연결
    d = client.get(f"{URL}/{po['id']}").json()["data"]
    assert received_from(d, "P1") == 50 and stock(client, po, "P1") == 50  # 누적 입고량·재고 모두 −20
    assert receive(client, po, ("P1", 50)).status_code == 201  # 정정으로 줄어든 만큼 다시 입고 가능 (50 + 50 = 100)


def test_receipt_correction_blocked_after_received(client, world, po):
    r = receive(client, po, ("P1", 100), ("P2", 50), ("P3", 10))
    assert r.json()["data"]["status"] == "RECEIVED"
    receipt_id = client.get("/api/v1/inventory-movements", params={"movement_type": "RECEIPT"}).json()["data"][0]["id"]
    r = client.post(f"/api/v1/inventory-movements/{receipt_id}/corrections", json={"quantity": 1, "reason": "오입력"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "INVALID_STATUS"  # RECEIVED 발주의 입고는 정정 불가 (한계)


def received_from(order, sku):
    return next(i for i in order["items"] if i["product_sku"] == sku)["received_quantity"]  # 응답 data 에서 누적 입고량


# ----- 회사 분리 -----
def test_other_company_404(client, world, po):
    login_as(client, "staff@b.test")
    assert receive(client, po, ("P1", 1)).status_code == 404
