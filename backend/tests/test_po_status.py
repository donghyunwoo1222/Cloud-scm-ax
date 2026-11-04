"""발주 상태 변경 API (#34) 테스트: approve·order·cancel. 동시 요청은 test_concurrency.py."""

import pytest  # 테스트 도구

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem, Supplier  # 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/purchase-orders"  # 발주 경로


@pytest.fixture
def po(client, world, session):
    """회사 A 의 DRAFT 발주서 하나(품목 P1 100개)를 담당자로 만들어 둔다 → 응답 data."""
    product = Product(company_id=world["a_company"].id, sku="P1", name="품목1", unit="개", unit_cost=1000,
                      default_supplier_id=world["a_supplier"].id)
    session.add(product)
    session.commit()
    login_as(client)  # 담당자
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": product.id, "quantity": 100, "unit_price": 800}]})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def act(client, po, action):
    """상태 변경 요청 (본문 없음)."""
    return client.post(f"{URL}/{po['id']}/{action}")


def code(response):
    return response.status_code, response.json()["error"]["code"]  # (HTTP, 오류 코드)


def set_status(session, po, status):
    """테스트 준비용: 상태를 직접 바꾼다 (RECEIVED 는 #35 입고가 만든다)."""
    session.get(PurchaseOrder, po["id"]).status = status
    session.commit()


def add_receipt(session, world, po, mtype="RECEIPT", direction="IN", qty=40, **extra):
    """발주 줄에 연결된 이력을 직접 넣는다 (입고 API 는 #35) → 이력."""
    item = session.get(PurchaseOrderItem, po["items"][0]["id"])
    m = InventoryMovement(company_id=item.company_id, product_id=item.product_id, created_by=world["a_staff"].id, movement_type=mtype,
                          direction=direction, quantity=qty, movement_date=seoul_today(), purchase_order_item_id=item.id, **extra)
    session.add(m)
    session.commit()
    return m


# ----- 완료 기준 1: 허용된 이동만 -----
def test_happy_path_approve_then_order(client, world, po):
    login_as(client, "admin@a.test")
    d = act(client, po, "approve").json()["data"]
    assert d["status"] == "APPROVED" and d["approved_by"] == world["a_admin"].id and d["approved_at"] is not None
    login_as(client)  # 발주 표시는 담당자도 된다
    d = act(client, po, "order").json()["data"]
    assert d["status"] == "ORDERED" and d["ordered_at"] is not None


def test_disallowed_moves(client, world, po, session):
    login_as(client, "admin@a.test")
    assert code(act(client, po, "order")) == (409, "INVALID_STATUS")  # DRAFT 에서 바로 발주
    act(client, po, "approve")
    assert code(act(client, po, "approve")) == (409, "INVALID_STATUS")  # 승인 두 번
    act(client, po, "order")
    assert code(act(client, po, "order")) == (409, "INVALID_STATUS")  # 발주 두 번
    set_status(session, po, "RECEIVED")
    assert code(act(client, po, "cancel")) == (409, "INVALID_STATUS")  # RECEIVED 취소
    set_status(session, po, "CANCELLED")
    for action in ("approve", "order", "cancel"):
        assert code(act(client, po, action)) == (409, "INVALID_STATUS")  # 취소된 발주는 끝
    assert client.patch(f"{URL}/{po['id']}", json={"memo": "x"}).status_code == 409  # 승인 이후 수정 불가 (#33)


@pytest.mark.parametrize("status", ["DRAFT", "APPROVED", "ORDERED"])
def test_cancel_without_receipt(client, world, po, session, status):
    set_status(session, po, status)
    d = act(client, po, "cancel").json()["data"]
    assert d["status"] == "CANCELLED" and d["cancelled_at"] is not None


def test_cancelled_draft_frees_supplier_slot(client, world, po):
    """DRAFT 를 취소하면 같은 공급업체에 새 DRAFT 를 만들 수 있다 (공급업체당 DRAFT 1장)."""
    act(client, po, "cancel")
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": po["items"][0]["product_id"], "quantity": 1, "unit_price": 1}]})
    assert r.status_code == 201


# ----- 완료 기준 2: S11 담당자의 approve 는 403 -----
def test_staff_cannot_approve(client, world, po):
    assert code(act(client, po, "approve")) == (403, "FORBIDDEN_ROLE")
    assert client.get(f"{URL}/{po['id']}").json()["data"]["status"] == "DRAFT"


# ----- 완료 기준 3: 비활성이 든 DRAFT 승인은 INACTIVE_REFERENCE -----
def test_approve_blocked_by_inactive_product(client, world, po, session):
    session.get(Product, po["items"][0]["product_id"]).is_active = False
    session.commit()
    login_as(client, "admin@a.test")
    r = act(client, po, "approve")
    assert code(r) == (409, "INACTIVE_REFERENCE") and "P1" in r.json()["error"]["message"]
    assert client.get(f"{URL}/{po['id']}").json()["data"]["status"] == "DRAFT"


def test_approve_blocked_by_inactive_supplier(client, world, po, session):
    session.get(Supplier, world["a_supplier"].id).is_active = False
    session.commit()
    login_as(client, "admin@a.test")
    assert code(act(client, po, "approve")) == (409, "INACTIVE_REFERENCE")


def test_inactive_after_approval_does_not_block_order(client, world, po, session):
    """승인 뒤에 품목이 비활성이 되어도 발주 표시는 된다 (비활성은 새 발주에만 영향)."""
    login_as(client, "admin@a.test")
    act(client, po, "approve")
    session.get(Product, po["items"][0]["product_id"]).is_active = False
    session.commit()
    assert act(client, po, "order").json()["data"]["status"] == "ORDERED"


# ----- 완료 기준 5: 입고 40 → 정정 40 이어도 취소 불가 -----
def test_cannot_cancel_after_receipt_even_if_fully_corrected(client, world, po, session):
    set_status(session, po, "ORDERED")
    receipt = add_receipt(session, world, po, qty=40)
    add_receipt(session, world, po, mtype="CORRECTION", direction="OUT", qty=40, reason="오입력", reverses_movement_id=receipt.id)
    assert client.get(f"{URL}/{po['id']}").json()["data"]["items"][0]["received_quantity"] == 0  # 누적 입고량은 0
    assert code(act(client, po, "cancel")) == (409, "CANNOT_CANCEL_RECEIVED")  # 그래도 입고 기록이 있으니 막는다
    assert client.get(f"{URL}/{po['id']}").json()["data"]["status"] == "ORDERED"


# ----- 회사 분리 -----
def test_other_company_order_is_404(client, world, po):
    for email in ("admin@b.test", "staff@b.test"):
        login_as(client, email)
        assert act(client, po, "cancel").status_code == 404
        assert act(client, po, "order").status_code == 404
    login_as(client, "admin@b.test")
    assert act(client, po, "approve").status_code == 404


def test_requires_login(client, world, po):
    client.post("/api/v1/auth/logout")
    assert act(client, po, "cancel").status_code == 401
