"""정정 이력 API (#30) 테스트: POST /inventory-movements/{id}/corrections. 준비 데이터 world 는 conftest."""

from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 합계, SELECT 문
from sqlalchemy.orm import aliased  # 같은 표를 두 번 쓰기 (정정 ↔ 원래 이력)

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product, PurchaseOrder, PurchaseOrderItem  # 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/inventory-movements"  # 입출고 경로


@pytest.fixture
def products(world, session):
    """회사 A·B 에 품목 하나씩 (이력 없음 → 재고 0)."""
    out = {}
    for key in ("a", "b"):
        product = Product(company_id=world[f"{key}_company"].id, sku=f"{key.upper()}-1", name="품목", unit="개",
                          unit_cost=1000, default_supplier_id=world[f"{key}_supplier"].id)
        session.add(product)
        out[key] = product
    session.commit()  # 준비 데이터 확정 (409·422 뒤 rollback 해도 남는다)
    return out


def move(client, product, movement_type, quantity, **fields):
    """입출고 등록 → 이력 id. 판매면 채널을 붙인다."""
    if movement_type == "SALE":
        fields.setdefault("sales_channel", "OWN_MALL")
    response = client.post(URL, json={"product_id": product.id, "movement_type": movement_type, "quantity": quantity, **fields})
    assert response.status_code == 201, response.json()
    return response.json()["data"]["id"]


def correct(client, movement_id, quantity, reason="수량 오입력"):
    """정정 요청."""
    body = {"quantity": quantity} if reason is None else {"quantity": quantity, "reason": reason}
    return client.post(f"{URL}/{movement_id}/corrections", json=body)


# ----- 정상 정정 -----
def test_correct_sale_increases_stock(client, world, products):
    """입고 200, 판매 100(실제 10) → 정정 90: 재고는 100 → 190, 정정 행은 원래를 가리키고 방향 IN·날짜는 원래와 같다."""
    login_as(client)
    p = products["a"]
    move(client, p, "RECEIPT", 200)
    last_week = (seoul_today() - timedelta(days=7)).isoformat()
    sale_id = move(client, p, "SALE", 100, movement_date=last_week)  # 일주일 전 판매로 잘못 입력
    response = correct(client, sale_id, 90)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["movement_type"] == "CORRECTION" and data["direction"] == "IN"  # 원래(OUT)의 반대
    assert data["reverses_movement_id"] == sale_id  # 원래 이력을 가리킨다
    assert data["movement_date"] == last_week  # 원래 이력의 날짜를 따른다
    assert data["sales_channel"] is None  # 정정에는 채널이 없다
    assert data["stock_after"] == 190  # 200 − 100 + 90 (재고는 −10만큼만 줄었다)


def test_correct_receipt_decreases_stock(client, world, products):
    """직접 입고 50(실제 30) → 정정 20: 재고 30, 방향 OUT. 발주 없는 입고는 상태 검사 없이 정정된다."""
    login_as(client)
    receipt_id = move(client, products["a"], "RECEIPT", 50)
    response = correct(client, receipt_id, 20)
    assert response.status_code == 201
    assert response.json()["data"]["direction"] == "OUT"
    assert response.json()["data"]["stock_after"] == 30


def test_correct_adjustment(client, world, products):
    """실사 조정도 정정할 수 있다: 감소 조정 30(실제 3) → 정정 27 → 재고 97."""
    login_as(client)
    move(client, products["a"], "RECEIPT", 100)
    adj_id = move(client, products["a"], "ADJUSTMENT", 30, direction="OUT", reason="실사 차이")
    response = correct(client, adj_id, 27)
    assert response.status_code == 201
    assert response.json()["data"]["stock_after"] == 97  # 100 − 30 + 27


def test_increase_adjustment_correction_cannot_make_stock_negative(client, world, products):
    """증가 조정 +30 → 판매 25(남은 5) → 조정 정정 27 이면 재고 −22 가 되므로 409 (정정 방향 OUT 도 잠금·음수 검사를 거친다)."""
    login_as(client)
    adj_id = move(client, products["a"], "ADJUSTMENT", 30, direction="IN", reason="실사 차이")  # 재고 30
    move(client, products["a"], "SALE", 25)  # 재고 5
    response = correct(client, adj_id, 27)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert response.json()["error"]["details"] == {"current_stock": 5, "requested": 27}
    assert correct(client, adj_id, 5).json()["data"]["stock_after"] == 0  # 남은 재고만큼은 정정된다


def test_inactive_product_correction_allowed(client, world, products):
    """비활성 품목이어도 정정은 허용한다."""
    login_as(client)
    receipt_id = move(client, products["a"], "RECEIPT", 10)
    client.patch(f"/api/v1/products/{products['a'].id}", json={"is_active": False})
    assert correct(client, receipt_id, 5).status_code == 201


# ----- 거절 규칙 -----
def test_correction_of_correction_is_422(client, world, products):
    """정정의 정정은 422."""
    login_as(client)
    receipt_id = move(client, products["a"], "RECEIPT", 10)
    correction_id = correct(client, receipt_id, 2).json()["data"]["id"]
    response = correct(client, correction_id, 1)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_exceeding_original_is_409(client, world, products):
    """판매 10 에 정정 6 → 남은 4 까지만. 정정 5 는 409 CORRECTION_EXCEEDS, 정정 4 는 된다."""
    login_as(client)
    move(client, products["a"], "RECEIPT", 100)
    sale_id = move(client, products["a"], "SALE", 10)
    assert correct(client, sale_id, 6).status_code == 201
    over = correct(client, sale_id, 5)  # 6 + 5 = 11 > 10
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "CORRECTION_EXCEEDS"
    assert over.json()["error"]["details"] == {"original_quantity": 10, "already_corrected": 6, "requested": 5}
    assert correct(client, sale_id, 4).status_code == 201  # 6 + 4 = 10 (원래 수량까지는 된다)


@pytest.mark.parametrize(
    "body",
    [{"quantity": 1}, {"quantity": 1, "reason": "   "}, {"quantity": 0, "reason": "x"}, {"quantity": 1.0, "reason": "x"},
     {"quantity": 1, "reason": "x", "direction": "OUT"}],
    ids=["no-reason", "blank-reason", "quantity-0", "quantity-float", "extra-field"],
)
def test_invalid_body_is_422(client, world, products, body):
    """사유 없음·공백, 수량 0·소수, 방향 같은 모르는 칸은 422."""
    login_as(client)
    receipt_id = move(client, products["a"], "RECEIPT", 10)
    assert client.post(f"{URL}/{receipt_id}/corrections", json=body).status_code == 422


def test_receipt_correction_cannot_make_stock_negative(client, world, products):
    """입고 50 → 판매 40(남은 10) → 입고 정정 20 이면 재고 −10 이 되므로 409 INSUFFICIENT_STOCK."""
    login_as(client)
    receipt_id = move(client, products["a"], "RECEIPT", 50)
    move(client, products["a"], "SALE", 40)
    response = correct(client, receipt_id, 20)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INSUFFICIENT_STOCK"
    assert response.json()["error"]["message"] == "현재고 10개보다 많이 줄일 수 없습니다."


def test_other_company_movement_is_404(client, world, products):
    """B 회사 이력을 A 가 정정하면 없는 id 와 같은 404."""
    login_as(client, "staff@b.test")
    b_receipt = move(client, products["b"], "RECEIPT", 10)  # B 의 이력
    login_as(client)  # A 로 다시 로그인
    other = correct(client, b_receipt, 1)
    missing = correct(client, 999999, 1)
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


# ----- 발주 입고 정정: 발주가 ORDERED 일 때만 -----
@pytest.fixture
def po_receipt(world, session, products):
    """회사 A 의 발주(수량 100) 품목에 연결된 입고 40 이력. 발주 상태는 테스트가 바꾼다."""
    order = PurchaseOrder(company_id=world["a_company"].id, supplier_id=world["a_supplier"].id, po_number="PO-1",
                          status="ORDERED", created_by=world["a_admin"].id)
    session.add(order)
    session.flush()  # order.id 생성
    item = PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=products["a"].id,
                             quantity=100, unit_price=1000)
    session.add(item)
    session.flush()  # item.id 생성
    receipt = InventoryMovement(company_id=order.company_id, product_id=products["a"].id, created_by=world["a_admin"].id,
                                movement_type="RECEIPT", direction="IN", quantity=40, movement_date=seoul_today(),
                                purchase_order_item_id=item.id)  # 발주 입고 API(#35)가 쓸 모양 그대로
    session.add(receipt)
    session.commit()
    return {"order": order, "item": item, "receipt": receipt}


def test_po_receipt_correction_when_ordered(client, world, po_receipt):
    """발주가 ORDERED 면 정정되고, 정정 행도 같은 발주 품목을 가리킨다 (누적 입고량 = 입고 − 정정)."""
    login_as(client)
    response = correct(client, po_receipt["receipt"].id, 10)
    assert response.status_code == 201
    assert response.json()["data"]["purchase_order_item_id"] == po_receipt["item"].id


@pytest.mark.parametrize("status", ["RECEIVED", "CANCELLED"])
def test_po_receipt_correction_blocked_unless_ordered(client, world, po_receipt, session, status):
    """발주가 ORDERED 가 아니면 409 INVALID_STATUS (RECEIVED 가 된 발주의 입고는 정정 불가)."""
    po_receipt["order"].status = status
    session.commit()
    login_as(client)
    response = correct(client, po_receipt["receipt"].id, 10)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_STATUS"


# ----- S13: 판매 정정 후 순판매·재고 -----
def test_s13_sale_correction_net_sales(client, world, products, session):
    """S13: 판매 100 + 정정 90 → 순판매 10, 재고는 −10 만큼만 줄었다 (현재고 = 이력 합계).

    추천 계산 함수(#38~)는 아직 없으므로, erd.md 조회 2)와 같은 방식(판매 − 그 판매를 가리키는 정정)으로 이력에서 직접 구한다.
    """
    login_as(client)
    p = products["a"]
    move(client, p, "RECEIPT", 300)
    sale_id = move(client, p, "SALE", 100)
    stock_after = correct(client, sale_id, 90).json()["data"]["stock_after"]
    assert stock_after == 290  # 300 − 100 + 90

    sale, fix = InventoryMovement, aliased(InventoryMovement)  # 판매 이력, 그 판매를 가리키는 정정 이력
    corrected = (select(fix.reverses_movement_id, func.sum(fix.quantity).label("q"))
                 .where(fix.movement_type == "CORRECTION").group_by(fix.reverses_movement_id).subquery())  # 원래 이력별 정정 합계
    net_sales = session.scalar(
        select(func.coalesce(func.sum(sale.quantity - func.coalesce(corrected.c.q, 0)), 0))
        .outerjoin(corrected, corrected.c.reverses_movement_id == sale.id)
        .where(sale.company_id == p.company_id, sale.product_id == p.id, sale.movement_type == "SALE",
               sale.movement_date.between(seoul_today() - timedelta(days=29), seoul_today()))  # 오늘 포함 30일, 원래 판매 날짜 기준
    )
    assert net_sales == 10  # 100 − 90
