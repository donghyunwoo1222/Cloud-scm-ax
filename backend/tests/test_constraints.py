"""DB 제약 테스트: 잘못된 행은 DB가 거절하고, 올바른 행은 받아들이는지 확인한다."""

import pytest  # 테스트 도구
from sqlalchemy.exc import IntegrityError  # 제약 위반 시 나는 오류

from app.models import (  # 표 모델들
    Company,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)


def add(session, obj):
    """행 하나를 DB에 넣는다 (flush: 트랜잭션 안에서 실제 INSERT 실행)."""
    session.add(obj)  # 세션에 올리고
    session.flush()  # DB에 보낸다 → 제약 위반이면 여기서 오류
    return obj  # id 가 채워진 객체를 돌려준다


def rejected(session, obj) -> bool:
    """행을 넣어 보고 DB가 거절하면 True. 실패한 INSERT만 되돌리고 테스트는 이어 간다."""
    try:
        with session.begin_nested():  # 세이브포인트: 실패해도 이 안의 작업만 되돌린다
            add(session, obj)  # 넣어 본다
    except IntegrityError:  # 제약 위반이면
        return True  # 거절됨
    return False  # 들어갔으면 거절 안 됨


@pytest.fixture
def base(session):
    """테스트마다 필요한 기본 행: 회사, 사용자, 공급업체, 품목, 발주서와 발주 품목."""
    company = add(session, Company(name="가나상사"))  # 회사
    user = add(session, User(company_id=company.id, name="관리자", email="admin@ga.na", password_hash="x", role="ADMIN"))  # 사용자
    supplier = add(session, Supplier(company_id=company.id, name="다라유통", lead_time_days=5))  # 공급업체 (리드타임 5일)
    product = add(
        session,
        Product(company_id=company.id, sku="A-001", name="생수", unit="박스", unit_cost=3000, default_supplier_id=supplier.id),  # 품목
    )
    order = add(session, PurchaseOrder(company_id=company.id, supplier_id=supplier.id, po_number="PO-1", created_by=user.id))  # DRAFT 발주서
    item = add(
        session,
        PurchaseOrderItem(company_id=company.id, purchase_order_id=order.id, product_id=product.id, quantity=100, unit_price=3000),  # 발주 품목
    )
    return {"company": company, "user": user, "supplier": supplier, "product": product, "order": order, "item": item}


def movement(base, **fields):
    """기본값이 채워진 입출고 이력 한 줄 (판매 10개). 테스트마다 바꿀 칸만 넘긴다."""
    values = {
        "company_id": base["company"].id,  # 회사
        "product_id": base["product"].id,  # 품목
        "created_by": base["user"].id,  # 등록자
        "movement_type": "SALE",  # 판매 출고
        "direction": "OUT",  # 줄임
        "quantity": 10,  # 10개
        "sales_channel": "SMARTSTORE",  # 판매 채널
    }
    values.update(fields)  # 테스트가 준 값으로 덮어쓴다
    return InventoryMovement(**values)  # 아직 DB에 넣지 않은 이력 객체


def test_valid_rows_are_accepted(session, base):
    """기준선: 올바른 판매·입고·정정은 들어가야 한다 (거절 테스트가 우연히 통과하지 않았다는 확인)."""
    sale = add(session, movement(base))  # 정상 판매 10개
    add(session, movement(base, movement_type="RECEIPT", direction="IN", sales_channel=None, purchase_order_item_id=base["item"].id))  # 발주 입고
    add(
        session,
        movement(base, movement_type="CORRECTION", direction="IN", quantity=9, sales_channel=None, reverses_movement_id=sale.id, reason="수량 오입력"),  # 판매 정정
    )


@pytest.mark.parametrize(
    "fields",
    [
        pytest.param({"quantity": 0}, id="1-quantity-0"),  # 1) 수량 0
        pytest.param({"sales_channel": None}, id="2-sale-without-channel"),  # 2) 판매인데 채널 없음
        pytest.param({"movement_type": "ADJUSTMENT", "sales_channel": None, "reason": None}, id="3-adjustment-without-reason"),  # 3) 조정인데 사유 없음
        pytest.param({"movement_type": "CORRECTION", "direction": "IN", "sales_channel": None, "reason": "오입력"}, id="4-correction-without-target"),  # 4) 정정인데 원래 이력 없음
        pytest.param({"purchase_order_item_id": "ITEM"}, id="5-sale-with-po-item"),  # 5) 판매에 발주 품목 연결
        pytest.param({"direction": "IN"}, id="sale-direction-in"),  # 판매인데 늘림
        pytest.param({"reverses_movement_id": "SELF_SALE"}, id="non-correction-with-target"),  # 정정이 아닌데 원래 이력을 가리킴
    ],
)
def test_chk_movement_rejects_invalid_rows(session, base, fields):
    """chk_movement 가 잘못된 이력 한 줄을 거절한다."""
    if fields.get("purchase_order_item_id") == "ITEM":  # 발주 품목 id 는 base 를 만든 뒤에야 알 수 있어 여기서 채운다
        fields = {**fields, "purchase_order_item_id": base["item"].id}
    if fields.get("reverses_movement_id") == "SELF_SALE":  # 가리킬 원래 이력을 먼저 하나 만든다
        fields = {**fields, "reverses_movement_id": add(session, movement(base)).id}
    assert rejected(session, movement(base, **fields))  # 거절돼야 한다


def test_one_draft_per_supplier(session, base):
    """6) 같은 공급업체에 DRAFT 2장은 거절, 첫 장이 DRAFT가 아니게 되면 새 DRAFT 허용."""
    second = PurchaseOrder(company_id=base["company"].id, supplier_id=base["supplier"].id, po_number="PO-2", created_by=base["user"].id)  # 두 번째 DRAFT
    assert rejected(session, second)  # 부분 고유 인덱스가 막는다
    base["order"].status = "APPROVED"  # 첫 발주서를 승인 상태로
    session.flush()  # DB에 반영
    third = PurchaseOrder(company_id=base["company"].id, supplier_id=base["supplier"].id, po_number="PO-3", created_by=base["user"].id)  # 다시 DRAFT
    assert not rejected(session, third)  # DRAFT끼리만 검사하므로 이제는 들어간다


def test_sku_unique_per_company(session, base):
    """7) 같은 회사 같은 SKU는 거절, 다른 회사면 같은 SKU 허용."""
    supplier_id = base["supplier"].id  # 같은 회사 공급업체
    same = Product(company_id=base["company"].id, sku="A-001", name="생수2", unit="개", unit_cost=0, default_supplier_id=supplier_id)  # 같은 회사, 같은 SKU
    assert rejected(session, same)  # 거절

    other = add(session, Company(name="마바상사"))  # 다른 회사
    other_supplier = add(session, Supplier(company_id=other.id, name="다라유통", lead_time_days=3))  # 업체명도 회사가 다르면 허용
    other_product = Product(company_id=other.id, sku="A-001", name="생수", unit="박스", unit_cost=0, default_supplier_id=other_supplier.id)  # 다른 회사, 같은 SKU
    assert not rejected(session, other_product)  # 허용
