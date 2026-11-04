"""입출고 등록 API (#29) 테스트. 준비 데이터 world 는 conftest. 동시 출고는 test_concurrency.py."""

from datetime import timedelta  # 날짜 더하기·빼기

import pytest  # 테스트 도구

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import Product  # 품목 표
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/inventory-movements"  # 입출고 등록 경로


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


def post(client, product, **fields):
    """입출고 등록 요청 (기본: 판매 1개, 자사몰)."""
    body = {"product_id": product.id, "movement_type": "SALE", "quantity": 1, "sales_channel": "OWN_MALL", **fields}
    return client.post(URL, json={k: v for k, v in body.items() if v is not None})  # None 칸은 보내지 않는다


def receive(client, product, quantity):
    """직접 입고 (재고 채우기)."""
    return post(client, product, movement_type="RECEIPT", quantity=quantity, sales_channel=None)


# ----- 완료 기준 1: 직접 입고·출고 3종·조정을 등록할 수 있다 -----
def test_register_all_types(client, world, products):
    """입고 100 → 판매 30 → 폐기 5 → 기타 5 → 조정 −3 → 조정 +2 = 59. 방향은 서버가 정한다."""
    login_as(client)
    p = products["a"]
    first = receive(client, p, 100)
    assert first.status_code == 201
    data = first.json()["data"]
    assert data["direction"] == "IN" and data["stock_after"] == 100
    assert data["movement_date"] == seoul_today().isoformat()  # 날짜를 비우면 서울 기준 오늘

    steps = [  # (보낼 칸, 기대 방향, 기대 재고)
        ({"movement_type": "SALE", "quantity": 30}, "OUT", 70),
        ({"movement_type": "DISPOSAL", "quantity": 5, "sales_channel": None}, "OUT", 65),
        ({"movement_type": "OTHER_OUT", "quantity": 5, "sales_channel": None}, "OUT", 60),
        ({"movement_type": "ADJUSTMENT", "quantity": 3, "direction": "OUT", "reason": "실사 차이", "sales_channel": None}, "OUT", 57),
        ({"movement_type": "ADJUSTMENT", "quantity": 2, "direction": "IN", "reason": "실사 차이", "sales_channel": None}, "IN", 59),
    ]
    for fields, direction, stock in steps:
        response = post(client, p, **fields)
        assert response.status_code == 201, response.json()
        assert response.json()["data"]["direction"] == direction
        assert response.json()["data"]["stock_after"] == stock


def test_past_date_allowed_future_rejected(client, world, products):
    """어제 날짜는 받고, 내일 날짜는 422 (아직 일어나지 않은 입출고가 재고·추천에 섞이지 않게)."""
    login_as(client)
    yesterday = (seoul_today() - timedelta(days=1)).isoformat()
    tomorrow = (seoul_today() + timedelta(days=1)).isoformat()
    assert receive(client, products["a"], 10).status_code == 201
    assert post(client, products["a"], movement_date=yesterday).status_code == 201
    future = post(client, products["a"], movement_date=tomorrow)
    assert future.status_code == 422
    assert future.json()["error"]["details"][0]["field"] == "movement_date"


def test_inactive_product_still_allowed(client, world, products):
    """비활성 품목도 직접 입고·출고·조정은 된다 (남은 재고 처리, 반품)."""
    login_as(client)
    p = products["a"]
    client.patch(f"/api/v1/products/{p.id}", json={"is_active": False})  # 품목 비활성
    assert receive(client, p, 5).status_code == 201
    assert post(client, p, quantity=2).status_code == 201
    assert post(client, p, movement_type="ADJUSTMENT", direction="OUT", quantity=1, reason="파손 확인",
                sales_channel=None).status_code == 201


# ----- 완료 기준 2: 재고보다 큰 출고·감소 조정은 INSUFFICIENT_STOCK -----
@pytest.mark.parametrize(
    "fields",
    [
        {"movement_type": "SALE"},
        {"movement_type": "DISPOSAL", "sales_channel": None},
        {"movement_type": "ADJUSTMENT", "direction": "OUT", "reason": "실사 차이", "sales_channel": None},
    ],
    ids=["sale", "disposal", "adjust-out"],
)
def test_insufficient_stock(client, world, products, fields):
    """재고 52에 60 출고 → 409, 현재고·요청 수량을 details 에. 52 는 정확히 0 까지 출고 가능."""
    login_as(client)
    p = products["a"]
    receive(client, p, 52)
    over = post(client, p, quantity=60, **fields)
    assert over.status_code == 409
    assert over.json()["error"] == {
        "code": "INSUFFICIENT_STOCK",
        "message": "현재고 52개보다 많이 출고할 수 없습니다.",
        "details": {"current_stock": 52, "requested": 60},
    }
    exact = post(client, p, quantity=52, **fields)  # 남은 재고를 딱 맞게
    assert exact.json()["data"]["stock_after"] == 0  # 0 은 허용 (음수만 막는다)


def test_first_movement_cannot_be_outbound(client, world, products):
    """이력이 하나도 없는 품목(재고 0)의 출고는 1개도 막힌다."""
    login_as(client)
    response = post(client, products["a"])
    assert response.status_code == 409
    assert response.json()["error"]["details"] == {"current_stock": 0, "requested": 1}


# ----- 완료 기준 4: purchase_order_item_id 나 CORRECTION 을 보내면 422 -----
@pytest.mark.parametrize(
    "fields",
    [
        {"movement_type": "RECEIPT", "sales_channel": None, "purchase_order_item_id": 1},  # 발주 입고는 #35 경로
        {"movement_type": "CORRECTION", "sales_channel": None, "reason": "오입력", "direction": "IN"},  # 정정은 #30 경로
    ],
    ids=["po-item", "correction"],
)
def test_bypass_fields_rejected(client, world, products, fields):
    """초과 입고·정정 규칙을 이 경로로 우회할 수 없다."""
    login_as(client)
    response = post(client, products["a"], **fields)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


# ----- 입력 규칙 -----
@pytest.mark.parametrize(
    "fields, field",
    [
        ({"sales_channel": None}, "sales_channel"),  # 판매인데 채널 없음
        ({"movement_type": "DISPOSAL"}, "sales_channel"),  # 판매가 아닌데 채널 있음
        ({"movement_type": "ADJUSTMENT", "sales_channel": None, "reason": "실사"}, "direction"),  # 조정인데 방향 없음
        ({"movement_type": "ADJUSTMENT", "sales_channel": None, "direction": "OUT"}, "reason"),  # 조정인데 사유 없음
        ({"movement_type": "ADJUSTMENT", "sales_channel": None, "direction": "OUT", "reason": "   "}, "reason"),  # 사유가 공백뿐
        ({"direction": "IN"}, "direction"),  # 판매에 방향을 보냄 (판매는 항상 OUT)
        ({"quantity": 0}, "quantity"),  # 수량 0
        ({"quantity": 1.5}, "quantity"),  # 소수
        ({"quantity": "3"}, "quantity"),  # 문자
    ],
    ids=["sale-no-channel", "disposal-channel", "adjust-no-direction", "adjust-no-reason", "adjust-blank-reason",
         "sale-direction", "quantity-0", "quantity-decimal", "quantity-string"],
)
def test_validation(client, world, products, fields, field):
    """규칙을 어기면 422, details 에 어느 칸인지."""
    login_as(client)
    receive(client, products["a"], 10)  # 재고 부족(409)이 아니라 입력 오류(422)가 나는지 보려고 재고를 채운다
    response = post(client, products["a"], **fields)
    assert response.status_code == 422, response.json()
    assert response.json()["error"]["details"][0]["field"] == field


# ----- 회사 분리·로그인 -----
def test_other_company_product_is_404(client, world, products):
    """본문의 product_id 가 B 회사 품목이면 404, details 에 칸 이름 (B 재고는 그대로)."""
    login_as(client)
    response = receive(client, products["b"], 10)
    assert response.status_code == 404
    assert response.json()["error"]["details"] == [{"field": "product_id", "reason": "not_found"}]


def test_anonymous_is_401(client, world, products):
    """로그인 안 함 → 401."""
    assert receive(client, products["a"], 1).status_code == 401
