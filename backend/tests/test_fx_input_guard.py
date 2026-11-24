"""FX_ENABLED 입력 가드 (#267): 꺼져 있으면 새 외화 값을 422 FX_DISABLED 로 거절하고, 켜져 있으면 지금처럼 동작한다."""

import pytest  # 테스트 도구

from app.config import settings  # 켜고 끄는 스위치 객체
from app.models import Product  # 품목 표
from tests.helpers import login_as  # 공통 로그인

PO = "/api/v1/purchase-orders"
SUP = "/api/v1/suppliers"


@pytest.fixture
def item(world, session):
    p = Product(company_id=world["a_company"].id, sku="G1", name="가드품목", unit="개", unit_cost=1000,
                default_supplier_id=world["a_supplier"].id)
    session.add(p)
    session.commit()
    return p


def body(world, item, **extra):
    line = {"product_id": item.id, "quantity": 1, "unit_price": 1000}
    return {"supplier_id": world["a_supplier"].id, "items": [line], **extra}


def assert_blocked(r):
    assert r.status_code == 422, r.json()
    err = r.json()["error"]
    assert err["code"] == "FX_DISABLED" and "원화(KRW)만" in err["message"]


@pytest.fixture
def fx_off(monkeypatch):
    monkeypatch.setattr(settings, "fx_enabled", False)


def test_off_blocks_usd_rate_and_fx_price_on_create(client, world, item, fx_off):
    login_as(client)
    fx_line = {"product_id": item.id, "quantity": 1, "fx_price": "1.00"}
    assert_blocked(client.post(PO, json=body(world, item, currency="USD")))  # 통화
    assert_blocked(client.post(PO, json=body(world, item, exchange_rate="1350")))  # 환율만
    assert_blocked(client.post(PO, json={"supplier_id": world["a_supplier"].id, "items": [fx_line]}))  # fx 단가만


def test_off_allows_krw_create_and_omitted_currency(client, world, item, fx_off):
    login_as(client)
    r = client.post(PO, json=body(world, item, currency="KRW"))
    assert r.status_code == 201 and r.json()["data"]["currency"] == "KRW"
    client.post(f"{PO}/{r.json()['data']['id']}/cancel")  # 같은 업체 DRAFT 는 하나뿐이라 비운다
    assert client.post(PO, json=body(world, item)).status_code == 201  # currency 생략


def test_off_blocks_patch_resending_fx_fields_but_allows_plain_edit(client, world, item, monkeypatch):
    login_as(client)
    monkeypatch.setattr(settings, "fx_enabled", True)  # 외화 초안을 켠 상태에서 만든다
    fx_line = {"product_id": item.id, "quantity": 1, "fx_price": "1.00"}
    d = client.post(PO, json={"supplier_id": world["a_supplier"].id, "items": [fx_line], "currency": "USD",
                              "exchange_rate": "1350"}).json()["data"]
    monkeypatch.setattr(settings, "fx_enabled", False)
    assert_blocked(client.patch(f"{PO}/{d['id']}", json={"exchange_rate": "1400"}))
    assert_blocked(client.patch(f"{PO}/{d['id']}", json={"currency": "USD", "items": [fx_line]}))
    assert client.patch(f"{PO}/{d['id']}", json={"memo": "메모만"}).status_code == 200  # 외화 칸 없는 수정은 통과
    assert client.get(f"{PO}/{d['id']}").status_code == 200  # 읽기
    login_as(client, "admin@a.test")
    assert client.post(f"{PO}/{d['id']}/approve").json()["data"]["status"] == "APPROVED"  # 승인


def test_off_supplier_currency(client, world, fx_off):
    login_as(client)
    r = client.post(SUP, json={"name": "외화업체", "lead_time_days": 3, "default_currency": "USD"})
    assert_blocked(r)
    ok = client.post(SUP, json={"name": "국내업체", "lead_time_days": 3})  # default_currency 키 없음
    assert ok.status_code == 201
    sid = ok.json()["data"]["id"]
    assert_blocked(client.patch(f"{SUP}/{sid}", json={"default_currency": "JPY"}))
    assert client.patch(f"{SUP}/{sid}", json={"memo": "키 없음"}).status_code == 200
    assert client.patch(f"{SUP}/{sid}", json={"default_currency": "KRW"}).status_code == 200


def test_on_allows_foreign_input(client, world, item, monkeypatch):
    monkeypatch.setattr(settings, "fx_enabled", True)
    login_as(client)
    assert client.post(SUP, json={"name": "외화업체", "lead_time_days": 3, "default_currency": "USD"}).status_code == 201
    fx_line = {"product_id": item.id, "quantity": 1, "fx_price": "1.00"}
    r = client.post(PO, json={"supplier_id": world["a_supplier"].id, "items": [fx_line], "currency": "USD"})
    assert r.status_code == 201 and r.json()["data"]["currency"] == "USD"
