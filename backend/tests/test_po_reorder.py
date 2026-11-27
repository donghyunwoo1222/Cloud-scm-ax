# ruff: noqa: F811  (product 픽스처를 다른 테스트 파일에서 가져와 인자로 쓴다)
"""이 발주서로 새 초안 만들기 테스트 (#188): 원본 상태별 복사, 이미 있는 초안, 제외 품목, 회사 분리, 외화·내부 값, 새 스냅샷."""

import json  # 문서 전체를 글자로 바꿔 내부 값을 찾는다

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 행 수 세기

from app.config import settings  # 외화 스위치
from app.models import InventoryMovement, Product, PurchaseOrder
from tests.helpers import login_as
from tests.test_po_transitions import (  # 발주서 만들기 도구
    STATES,
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
)

SECRET_EXTRA, SECRET_FREIGHT = "SECRET-EXTRA-188", 7654329  # 내부 전용 값의 표식
PUBLIC_TERMS = "PUBLIC-SPECIAL-188"  # 공급업체 문서에 나가야 하는 특약


def reorder(client, po_id, email="staff@a.test"):
    login_as(client, email)
    return client.post(f"{URL}/{po_id}/reorder")


@pytest.mark.parametrize("state", [s for s in STATES if s != "DRAFT"])
def test_copy_from_any_state_makes_new_draft(client, world, product, session, state):
    src = make_po(client, world, product, state)
    product.unit_cost = 1200  # 지금 마스터 단가 (원본 줄은 800원)
    session.commit()
    r = reorder(client, src["id"])
    assert r.status_code == 201, r.json()
    new, excluded = r.json()["data"], r.json()["excluded"]
    assert new["status"] == "DRAFT" and new["id"] != src["id"] and new["po_number"] != src["po_number"]
    assert new["source_po_id"] == src["id"] and excluded == []
    [line] = new["items"]
    assert line["quantity"] == 100 and line["unit_price"] == 1200  # 수량만 복사, 단가는 지금 값으로 새 스냅샷
    after = client.get(f"{URL}/{src['id']}").json()["data"]
    assert after["status"] == state and after["items"][0]["unit_price"] == 800 and after["source_po_id"] is None  # 원본은 그대로
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == (1 if state == "RECEIVED" else 0)  # 재고 이력은 원본의 입고뿐


def test_draft_source_points_to_itself(client, world, product):
    """원본이 DRAFT 면 그 업체의 초안이 바로 원본이라 새로 만들지 않고 원본으로 안내한다 (공급업체당 DRAFT 하나)."""
    src = make_po(client, world, product, "DRAFT")
    r = reorder(client, src["id"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_DRAFT"
    assert r.json()["error"]["details"]["purchase_order_id"] == src["id"]


def test_existing_draft_is_not_overwritten_and_double_click_makes_one(client, world, product, session):
    src = make_po(client, world, product, "RECEIVED")
    login_as(client)
    preview = client.get(f"{URL}/{src['id']}/reorder").json()["data"]
    assert preview["existing_draft"] is None and [i["sku"] for i in preview["items"]] == ["P1"]
    first = reorder(client, src["id"])
    second = reorder(client, src["id"])  # 연속 호출
    assert first.status_code == 201 and second.status_code == 409
    assert second.json()["error"]["code"] == "DUPLICATE_DRAFT"
    assert second.json()["error"]["details"]["purchase_order_id"] == first.json()["data"]["id"]
    assert session.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.status == "DRAFT")) == 1
    assert client.get(f"{URL}/{src['id']}/reorder").json()["data"]["existing_draft"]["id"] == first.json()["data"]["id"]  # 미리보기도 알린다


def test_other_company_gets_404(client, world, product):
    src = make_po(client, world, product, "RECEIVED")
    assert reorder(client, src["id"], "staff@b.test").status_code == 404
    assert client.get(f"{URL}/{src['id']}/reorder").status_code == 404
    assert reorder(client, 999999).status_code == 404


def test_inactive_product_is_excluded_and_reported(client, world, product, session):
    p2 = Product(company_id=world["a_company"].id, sku="P2", name="품목2", unit="개", unit_cost=500,
                 default_supplier_id=world["a_supplier"].id)
    session.add(p2)
    session.commit()
    login_as(client)
    src = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": [
        {"product_id": product.id, "quantity": 10, "unit_price": 800}, {"product_id": p2.id, "quantity": 7, "unit_price": 400}]}).json()["data"]
    client.post(f"{URL}/{src['id']}/cancel")  # 업체의 초안을 비워 복사할 수 있게
    p2.is_active = False
    session.commit()
    preview = client.get(f"{URL}/{src['id']}/reorder").json()["data"]
    assert [i["sku"] for i in preview["items"]] == ["P1"] and [(e["sku"], e["quantity"]) for e in preview["excluded"]] == [("P2", 7)]
    r = reorder(client, src["id"])
    assert r.status_code == 201 and [i["product_sku"] for i in r.json()["data"]["items"]] == ["P1"]
    assert [(e["sku"], e["quantity"]) for e in r.json()["excluded"]] == [("P2", 7)]


def test_all_inactive_or_inactive_supplier_is_refused(client, world, product, session):
    src = make_po(client, world, product, "RECEIVED")
    product.is_active = False
    session.commit()
    assert reorder(client, src["id"]).json()["error"]["code"] == "NO_COPYABLE_ITEMS"
    product.is_active = True
    world["a_supplier"].is_active = False
    session.commit()
    assert reorder(client, src["id"]).json()["error"]["code"] == "INACTIVE_REFERENCE"


def test_internal_values_and_fx_are_not_copied_and_supplier_document_stays_clean(client, world, product):
    login_as(client)
    src = client.post(URL, json={
        "supplier_id": world["a_supplier"].id, "items": [{"product_id": product.id, "quantity": 100, "unit_price": 800}],
        "freight_amount": SECRET_FREIGHT, "extra_costs": [{"name": SECRET_EXTRA, "amount": 6543217}],
        "special_terms": PUBLIC_TERMS, "payment_terms": "월말 현금", "freight_terms": "BILLED",
        "delivery_address": "서울 중구 1", "memo": "지난번 메모", "due_date": "2026-12-24"}).json()["data"]
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{src['id']}/approve")
    new = reorder(client, src["id"]).json()["data"]
    assert new["freight_amount"] is None and new["extra_costs"] == [] and new["krw_goods_total"] is None  # 내부 값은 비운다
    assert new["currency"] == "KRW" and new["exchange_rate"] is None
    assert new["special_terms"] == PUBLIC_TERMS and new["payment_terms"] == "월말 현금" and new["freight_terms"] == "BILLED"  # 문서에 나가는 조건은 복사
    assert new["delivery_address"] == "서울 중구 1" and new["memo"] is None and new["due_date"] is None  # 납기·메모는 새로
    login_as(client, "admin@a.test")
    assert client.post(f"{URL}/{new['id']}/approve").status_code == 200
    doc = json.dumps(client.get(f"{URL}/{new['id']}/document").json(), ensure_ascii=False)
    assert PUBLIC_TERMS in doc
    for secret in (SECRET_EXTRA, str(SECRET_FREIGHT), "7,654,329", "6543217", "6,543,217"):
        assert secret not in doc


def test_foreign_source_becomes_krw_draft_even_with_fx_off(client, world, product, monkeypatch):
    monkeypatch.setattr(settings, "fx_enabled", True)
    login_as(client)
    src = client.post(URL, json={"supplier_id": world["a_supplier"].id, "currency": "USD", "exchange_rate": "1350",
                                 "items": [{"product_id": product.id, "quantity": 5, "fx_price": "1.50"}]}).json()["data"]
    login_as(client, "admin@a.test")
    assert client.post(f"{URL}/{src['id']}/approve").status_code == 200
    monkeypatch.setattr(settings, "fx_enabled", False)  # 스위치를 끈 뒤에도 복사는 된다
    r = reorder(client, src["id"])
    assert r.status_code == 201, r.json()
    new = r.json()["data"]
    [line] = new["items"]
    assert new["currency"] == "KRW" and new["exchange_rate"] is None
    assert line["fx_unit_price"] is None and line["fx_box_unit_price"] is None and line["unit_price"] == 1000 and line["quantity"] == 5


def test_box_line_takes_new_factor_and_price(client, world, product, session):
    product.units_per_box, product.box_unit_cost, product.order_unit = 10, 9000, "박스"
    session.commit()
    login_as(client)
    src = client.post(URL, json={"supplier_id": world["a_supplier"].id,
                                 "items": [{"product_id": product.id, "box_quantity": 3}]}).json()["data"]
    client.post(f"{URL}/{src['id']}/cancel")
    product.units_per_box, product.box_unit_cost = 20, 17000  # 환산계수·박스 단가 변경
    session.commit()
    [line] = reorder(client, src["id"]).json()["data"]["items"]
    assert (line["box_quantity"], line["quantity"], line["units_per_box"], line["box_unit_price"]) == (3, 60, 20, 17000)  # 3박스 × 20개
    assert client.get(f"{URL}/{src['id']}").json()["data"]["items"][0]["quantity"] == 30  # 원본 줄은 그대로


def test_price_alert_still_works_on_copied_draft(client, world, product, session):
    src = make_po(client, world, product, "APPROVED")  # 지난 단가 800원
    product.unit_cost = 1000
    session.commit()
    new = reorder(client, src["id"]).json()["data"]
    line = new["items"][0]
    r = client.post(f"{URL}/price-check", json={"supplier_id": new["supplier_id"],
                                                "items": [{"product_id": line["product_id"], "unit_price": line["unit_price"]}]})
    assert r.json()["data"][0]["alert"]["direction"] == "UP" and r.json()["data"][0]["alert"]["percent"] == 25


def test_copy_is_recorded_in_change_log(client, world, product):
    src = make_po(client, world, product, "RECEIVED")
    new = reorder(client, src["id"]).json()["data"]
    rows = client.get(f"{URL}/{new['id']}/change-log").json()["data"]
    assert [(r["field"], r["new_value"]) for r in rows] == [("source_po_id", src["po_number"])]
