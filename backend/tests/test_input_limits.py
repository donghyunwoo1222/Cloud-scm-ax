"""큰 정수 입력 (#71 D): DB 정수 칸(최대 2,147,483,647)을 넘는 값이 500 이 아니라 422 가 되는지, 업무 상한이 맞는지."""

import pytest  # 테스트 도구
from pydantic import ValidationError  # 요청 모양 검사 실패

from app.models import Product  # 품목 표
from app.schemas.movements import CorrectionCreate, MovementCreate  # 입출고·정정 요청 모양
from app.schemas.products import ProductCreate  # 품목 요청 모양
from app.schemas.purchase_orders import ItemIn, ReceiptLine  # 발주 줄·입고 줄 요청 모양
from app.schemas.suppliers import SupplierCreate  # 공급업체 요청 모양
from tests.helpers import login_as  # 공통 로그인

TOO_BIG = 2**31  # DB integer 칸 최댓값 + 1


@pytest.fixture
def product(world, session):
    """회사 A 품목 하나 (요청이 검사를 통과하면 DB 까지 가도록 실제 id 를 쓴다)."""
    p = Product(company_id=world["a_company"].id, sku="BIG-1", name="큰수품목", unit="개", unit_cost=1000,
                default_supplier_id=world["a_supplier"].id)
    session.add(p)
    session.commit()  # 준비 데이터 확정
    return p


def cases(world, product):
    """(메서드, 경로, 본문, 문제 칸) 목록. 각 본문은 큰 수 칸 하나만 빼면 올바른 요청이다."""
    sid, pid = world["a_supplier"].id, product.id  # 실제 공급업체·품목 번호
    return [
        ("post", "/api/v1/suppliers", {"name": "큰수업체", "lead_time_days": TOO_BIG}, "lead_time_days"),
        ("patch", f"/api/v1/suppliers/{sid}", {"lead_time_days": TOO_BIG}, "lead_time_days"),
        ("post", "/api/v1/products", {"sku": "BIG-2", "name": "x", "unit": "개", "unit_cost": TOO_BIG,
                                      "default_supplier_id": sid}, "unit_cost"),
        ("post", "/api/v1/products", {"sku": "BIG-3", "name": "x", "unit": "개", "unit_cost": 1,
                                      "safety_stock": TOO_BIG, "default_supplier_id": sid}, "safety_stock"),
        ("patch", f"/api/v1/products/{pid}", {"unit_cost": TOO_BIG}, "unit_cost"),
        ("patch", f"/api/v1/products/{pid}", {"safety_stock": TOO_BIG}, "safety_stock"),
        ("post", "/api/v1/inventory-movements", {"product_id": pid, "movement_type": "RECEIPT", "quantity": TOO_BIG},
         "quantity"),
        ("post", "/api/v1/inventory-movements/1/corrections", {"quantity": TOO_BIG, "reason": "x"}, "quantity"),
        ("post", "/api/v1/purchase-orders", {"supplier_id": sid, "items": [
            {"product_id": pid, "quantity": TOO_BIG, "unit_price": 1}]}, "quantity"),
        ("post", "/api/v1/purchase-orders", {"supplier_id": sid, "items": [
            {"product_id": pid, "quantity": 1, "unit_price": TOO_BIG}]}, "unit_price"),
        ("post", "/api/v1/purchase-orders/1/receipts", {"items": [
            {"purchase_order_item_id": 1, "quantity": TOO_BIG}]}, "quantity"),
        # 본문의 번호 칸도 DB integer 로 비교되므로 범위를 넘으면 500 이었다
        ("post", "/api/v1/inventory-movements", {"product_id": TOO_BIG, "movement_type": "RECEIPT", "quantity": 1},
         "product_id"),
        ("post", "/api/v1/products", {"sku": "BIG-4", "name": "x", "unit": "개", "unit_cost": 1,
                                      "default_supplier_id": TOO_BIG}, "default_supplier_id"),
        ("post", "/api/v1/purchase-orders", {"supplier_id": TOO_BIG, "items": [
            {"product_id": pid, "quantity": 1, "unit_price": 1}]}, "supplier_id"),
        ("post", "/api/v1/purchase-orders", {"supplier_id": sid, "items": [
            {"product_id": TOO_BIG, "quantity": 1, "unit_price": 1}]}, "product_id"),
        ("post", "/api/v1/purchase-orders/1/receipts", {"items": [
            {"purchase_order_item_id": TOO_BIG, "quantity": 1}]}, "purchase_order_item_id"),
        # 경로·쿼리의 번호와 쪽 번호
        ("get", f"/api/v1/suppliers/{TOO_BIG}", None, "supplier_id"),
        ("get", f"/api/v1/products/{TOO_BIG}", None, "product_id"),
        ("get", f"/api/v1/stock/{TOO_BIG}", None, "product_id"),
        ("get", f"/api/v1/purchase-orders/{TOO_BIG}", None, "order_id"),
        ("post", f"/api/v1/purchase-orders/{TOO_BIG}/approve", None, "order_id"),
        ("patch", f"/api/v1/users/{TOO_BIG}", {"role": "STAFF"}, "user_id"),
        ("post", f"/api/v1/inventory-movements/{TOO_BIG}/corrections", {"quantity": 1, "reason": "x"}, "movement_id"),
        ("get", f"/api/v1/inventory-movements?product_id={TOO_BIG}", None, "product_id"),
        ("get", f"/api/v1/purchase-orders?supplier_id={TOO_BIG}", None, "supplier_id"),
        ("get", "/api/v1/suppliers?page=99999999", None, "page"),  # 쪽 번호 × 쪽 크기가 DB 범위를 넘는다
    ]


def test_too_big_integers_are_422(client, world, product):
    """DB 범위를 넘는 값은 DB 까지 가지 않고 422 VALIDATION_ERROR (전에는 DB 오류로 500 이었다)."""
    login_as(client, "admin@a.test")  # 공급업체 수정은 관리자만이라 관리자로
    wrong = []  # 422 가 아니었던 요청 (한 번에 모두 보이게 모은다)
    for method, path, body, field in cases(world, product):
        r = client.request(method.upper(), path, json=body)  # 본문이 없으면 json=None 이라 보내지 않는다
        if r.status_code != 422 or r.json()["error"]["code"] != "VALIDATION_ERROR" or field not in r.text:  # 칸 이름까지 알려줘야 한다
            wrong.append((method, path, field, r.status_code))
    assert wrong == []  # 500·201·404·409 가 하나도 없어야 한다


@pytest.mark.parametrize(("model", "base", "field", "limit"), [
    (SupplierCreate, {"name": "x"}, "lead_time_days", 365),  # 리드타임: 1년
    (ProductCreate, {"sku": "x", "name": "x", "unit": "개", "default_supplier_id": 1}, "unit_cost", 100_000_000),  # 단가: 1억 원
    (ProductCreate, {"sku": "x", "name": "x", "unit": "개", "unit_cost": 1, "default_supplier_id": 1},
     "safety_stock", 1_000_000),  # 안전재고: 100만 개
    (MovementCreate, {"product_id": 1, "movement_type": "RECEIPT"}, "quantity", 1_000_000),  # 입출고 수량: 100만 개
    (CorrectionCreate, {"reason": "x"}, "quantity", 1_000_000),  # 정정 수량
    (ItemIn, {"product_id": 1, "unit_price": 1}, "quantity", 1_000_000),  # 발주 수량
    (ItemIn, {"product_id": 1, "quantity": 1}, "unit_price", 100_000_000),  # 발주 단가
    (ReceiptLine, {"purchase_order_item_id": 1}, "quantity", 1_000_000),  # 입고 수량
])
def test_business_limits(model, base, field, limit):
    """상한까지는 받고, 상한 + 1 은 막는다 (예: 리드타임 365일 OK, 366일 422)."""
    model(**base, **{field: limit})  # 상한값은 통과
    with pytest.raises(ValidationError):
        model(**base, **{field: limit + 1})  # 하나 넘으면 실패 → API 에서 422
