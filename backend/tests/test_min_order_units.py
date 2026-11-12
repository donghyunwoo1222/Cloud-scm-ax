"""최소 주문량(MOQ, min_order_units) 테스트 (#194). 추천 계산은 test_recommend_calc.py(S20~S23), 추천 API 는 test_recommendations.py."""

import pytest  # 테스트 도구

from tests.helpers import login_as  # 공통 로그인
from tests.test_order_unit import ORDERS, PRODUCTS, new_product, order  # 박스 품목 본문·발주 도구


def test_product_saves_and_clears_moq(client, world):
    """등록 때 MOQ 5 저장, 수정에서 null 로 지우면 제한 없음. 보내지 않으면 기존 값 유지."""
    login_as(client)
    data = client.post(PRODUCTS, json=new_product(world, min_order_units=5)).json()["data"]
    assert data["min_order_units"] == 5
    url = f"{PRODUCTS}/{data['id']}"
    assert client.patch(url, json={"name": "새 이름"}).json()["data"]["min_order_units"] == 5
    assert client.patch(url, json={"min_order_units": None}).json()["data"]["min_order_units"] is None


def test_product_without_moq_is_null(client, world):
    """보내지 않으면 null (기존 품목과 같은 '제한 없음')."""
    login_as(client)
    assert client.post(PRODUCTS, json=new_product(world)).json()["data"]["min_order_units"] is None


@pytest.mark.parametrize("moq", [0, -1, 2.5, "5", 1_000_001])
def test_invalid_moq_is_422(client, world, moq):
    login_as(client)
    assert client.post(PRODUCTS, json=new_product(world, min_order_units=moq)).status_code == 422


def test_below_moq_order_is_allowed_and_snapshot_kept(client, world):
    """MOQ 5BOX 품목을 2BOX 로 발주해도 서버는 막지 않는다(화면이 확인만 받는다). 줄에는 당시 MOQ 가 남고 마스터를 바꿔도 그대로."""
    login_as(client)
    pid = client.post(PRODUCTS, json=new_product(world, order_unit="BOX", min_order_units=5)).json()["data"]["id"]
    po = order(client, world, pid, 2)  # 201 (막지 않음)
    [line] = po["items"]
    assert (line["box_quantity"], line["min_order_units"]) == (2, 5)
    client.patch(f"{PRODUCTS}/{pid}", json={"min_order_units": 10})  # 마스터 변경
    r = client.patch(f"{ORDERS}/{po['id']}", json={"items": [{"product_id": pid, "box_quantity": 3}]})  # DRAFT 다시 저장
    [line] = r.json()["data"]["items"]
    assert (line["box_quantity"], line["min_order_units"]) == (3, 5)  # 당시 값 유지
