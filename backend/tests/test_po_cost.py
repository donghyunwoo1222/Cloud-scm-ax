"""발주서 원가 칸 (#267 PR 1): 통화·환율·운송비·부대비용·특약, 공급업체 기본 조건, 승인 때 원화 고정, 입고 기준 원가.

숫자는 docs/06-system-design/money-rules.md 의 고정 숫자와 같다. 계산 규칙 자체는 test_po_money.py 가 검사하고, 여기서는 API·DB 를 거친 결과를 본다.
"""

import importlib.util  # 마이그레이션의 채워 넣기 SQL 을 불러온다
from pathlib import Path  # 마이그레이션 파일 위치

import pytest  # 테스트 도구
from sqlalchemy import select, text  # 조회, SQL 문장
from sqlalchemy.exc import IntegrityError  # DB CHECK 위반

from app.models import PoChangeLog, Product, PurchaseOrder  # 표
from app.services.po_money import CURRENCIES  # 통화 → (기준 단위, 소수 자리)
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/purchase-orders"
SUPPLIERS = "/api/v1/suppliers"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "e3c7a9f1b5d2_po_cost_fields.py"


def add_product(session, world, sku, key="a", **fields):
    p = Product(company_id=world[f"{key}_company"].id, sku=sku, name=f"품목{sku}", unit="개", unit_cost=1000,
                default_supplier_id=world[f"{key}_supplier"].id, **fields)
    session.add(p)
    session.flush()
    return p


@pytest.fixture
def items(world, session):
    """회사 A 품목 3개 + 3개입 박스 품목(박스 1,000원)."""
    out = {k: add_product(session, world, k) for k in ("P1", "P2", "P3")}
    out["BOX"] = add_product(session, world, "BOX", units_per_box=3, box_unit_cost=1000, order_unit="박스")
    session.commit()
    return out


def krw(p, qty, price):
    return {"product_id": p and p.id, "quantity": qty, "unit_price": price}  # p 가 None 이면 테스트가 나중에 채운다


def fx(p, qty, price, box=False):
    return {"product_id": p and p.id, ("box_quantity" if box else "quantity"): qty, "fx_price": price}


def create(client, world, *lines, **fields):
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": list(lines), **fields})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def approve_and_order(client, order_id):
    login_as(client, "admin@a.test")
    r = client.post(f"{URL}/{order_id}/approve")
    assert r.status_code == 200, r.json()
    return client.post(f"{URL}/{order_id}/order").json()["data"]


def receive(client, order, quantities):
    r = client.post(f"{URL}/{order['id']}/receipts", json={"items": [
        {"purchase_order_item_id": i["id"], "quantity": q} for i, q in zip(order["items"], quantities, strict=True) if q]})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


# ----- 기존 원화 발주서는 그대로 읽힌다 -----

def test_krw_order_defaults_and_cost(client, world, items):
    login_as(client)
    d = create(client, world, krw(items["P1"], 3, 1005))
    assert (d["currency"], d["rate_unit"], d["exchange_rate"], d["extra_costs"], d["freight_amount"]) == ("KRW", 1, None, [], None)
    assert d["items"][0]["line_total"] == 3015 and d["items"][0]["fx_unit_price"] is None
    assert d["cost"] == {"goods_fx_total": None, "goods_krw": 3015, "freight": None, "extras_total": 0, "total": 3015,
                         "missing": ["freight"], "received_goods_krw": None, "received_total": None}


def test_cost_sums_freight_and_extras(client, world, items):
    login_as(client)
    d = create(client, world, krw(items["P1"], 1380, 1000), freight_amount=120_000, freight_terms="BILLED",
               extra_costs=[{"name": "통관 수수료", "amount": 10_000}, {"name": "보험료", "amount": 20_000}])
    assert d["cost"]["total"] == 1_530_000 and d["cost"]["missing"] == [] and d["cost"]["extras_total"] == 30_000
    zero = client.patch(f"{URL}/{d['id']}", json={"freight_amount": 0}).json()["data"]  # 0 은 입력한 값
    assert zero["cost"]["missing"] == [] and zero["cost"]["total"] == 1_410_000


# ----- 외화: #282 고정 숫자가 API 에서도 같다 -----

def test_usd_rounds_once_on_total(client, world, items):
    login_as(client)
    d = create(client, world, fx(items["P1"], 1, "1"), fx(items["P2"], 1, "1"), fx(items["P3"], 1, "1"),
               currency="USD", exchange_rate="1350.75")
    assert d["cost"]["goods_krw"] == 4052 and d["cost"]["goods_fx_total"] == "3.00"  # 줄별 버림이면 4,050
    line = d["items"][0]
    assert (line["unit_price"], line["line_total"], line["fx_unit_price"], line["fx_line_total"]) == (None, None, "1.00", "1.00")  # 줄에는 원화 없음
    d = client.patch(  # 같은 업체 DRAFT 는 1장뿐이라 두 번째 예시는 수정으로 본다
f"{URL}/{d['id']}", json={"items": [fx(items["P1"], 3, "0.50")], "exchange_rate": "1350.25"}).json()["data"]
    assert d["cost"]["goods_krw"] == 2025  # 2,025.375 → 2,025


def test_jpy_rate_per_100(client, world, items):
    login_as(client)
    d = create(client, world, fx(items["P1"], 1, 10000), currency="JPY", exchange_rate="905.12")
    assert d["rate_unit"] == 100 and d["cost"]["goods_krw"] == 90512  # 10,000 × 905.12 ÷ 100


@pytest.mark.parametrize("lines, fields", [
    ([krw(None, 1, 1000)], {"exchange_rate": "1350"}),  # 원화에 환율
    ([krw(None, 1, 1000)], {"currency": "USD"}),  # 외화 줄에 원화 단가
    ([fx(None, 1, "0.035")], {"currency": "USD"}),  # 센트 미만 (지원하지 않는다)
    ([fx(None, 1, "0.5")], {"currency": "JPY"}),  # 엔 소수
    ([fx(None, 1, "1")], {"currency": "USD", "exchange_rate": "1350.255"}),  # 환율 소수 셋째 자리
    ([fx(None, 1, "1")], {"currency": "GBP"}),  # 지원하지 않는 통화
    ([fx(None, 1, "1")], {}),  # 원화 발주서에 외화 단가
    ([fx(None, 1, 1.5)], {"currency": "USD", "exchange_rate": 0}),  # 환율 0
    ([krw(None, 1, 1000)], {"extra_costs": [{"name": "포장", "amount": -1}]}),  # 음수 부대비용
    ([krw(None, 1, 1000)], {"extra_costs": [{"name": "x", "amount": 1}] * 21}),  # 부대비용 21줄
    ([krw(None, 1, 1000)], {"freight_terms": "FREE"}),  # 없는 운송비 조건
])
def test_invalid_money_is_422(client, world, items, lines, fields):
    login_as(client)
    for line in lines:
        line["product_id"] = items["P1"].id
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": lines, **fields})
    assert r.status_code == 422, r.json()


def test_currency_change_needs_items_and_resets_rate(client, world, items, session):
    login_as(client)
    d = create(client, world, fx(items["P1"], 2, "1.25"), currency="USD", exchange_rate="1350")
    r = client.patch(f"{URL}/{d['id']}", json={"currency": "KRW"})
    assert r.status_code == 422 and "items" in r.json()["error"]["message"]
    k = client.patch(f"{URL}/{d['id']}", json={"currency": "KRW", "items": [krw(items["P1"], 2, 1700)]}).json()["data"]
    assert (k["currency"], k["exchange_rate"], k["items"][0]["unit_price"], k["items"][0]["fx_unit_price"]) == ("KRW", None, 1700, None)
    rows = {(r.field, r.old_value, r.new_value) for r in session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == d["id"]))}
    assert {("currency", "USD", "KRW"), ("exchange_rate", "1350.00", None)} <= rows


def test_box_line_switches_currency_without_breaking_snapshot(client, world, items):
    login_as(client)
    d = create(client, world, {"product_id": items["BOX"].id, "box_quantity": 2})  # 원화 박스 줄 (2박스 = 6개, 2,000원)
    u = client.patch(f"{URL}/{d['id']}", json={"currency": "USD", "items": [fx(items["BOX"], 2, "10.01", box=True)]}).json()["data"]
    line = u["items"][0]
    assert (line["quantity"], line["box_unit_price"], line["fx_box_unit_price"], line["fx_line_total"]) == (6, None, "10.01", "20.02")


# ----- 공급업체 기본 조건: 만들 때 한 번 복사, 이후 바꿔도 그대로 -----

def test_supplier_defaults_are_copied_once(client, world, items):
    login_as(client)
    sid = world["a_supplier"].id
    s = client.patch(f"{SUPPLIERS}/{sid}", json={"default_currency": "USD", "default_freight_terms": "FOB",
                                                 "default_special_terms": "불량 3% 이내 무상 교환"}).json()["data"]
    assert (s["default_currency"], s["default_freight_terms"]) == ("USD", "FOB")
    d = create(client, world, fx(items["P1"], 1, "2"))
    assert (d["currency"], d["freight_terms"], d["special_terms"]) == ("USD", "FOB", "불량 3% 이내 무상 교환")
    client.patch(f"{SUPPLIERS}/{sid}", json={"default_freight_terms": "CIF", "default_special_terms": None})
    again = client.get(f"{URL}/{d['id']}").json()["data"]
    assert (again["freight_terms"], again["special_terms"]) == ("FOB", "불량 3% 이내 무상 교환")  # 이미 만든 발주서는 그대로
    assert client.patch(f"{SUPPLIERS}/{sid}", json={"default_currency": None}).status_code == 422  # 통화는 비울 수 없다


def test_explicit_null_overrides_supplier_default(client, world, items):
    login_as(client)
    client.patch(f"{SUPPLIERS}/{world['a_supplier'].id}", json={"default_freight_terms": "FOB", "default_special_terms": "특약"})
    d = create(client, world, krw(items["P1"], 1, 1000), freight_terms=None, special_terms="")
    assert (d["freight_terms"], d["special_terms"]) == (None, None)


# ----- 승인 때 원화 고정 -----

def test_approval_needs_rate_and_freezes_krw(client, world, items, session):
    login_as(client)
    d = create(client, world, fx(items["P1"], 3, "0.50"), currency="USD")
    assert d["cost"]["goods_krw"] is None and d["cost"]["missing"] == ["exchange_rate", "freight"]
    login_as(client, "admin@a.test")
    r = client.post(f"{URL}/{d['id']}/approve")
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "exchange_rate"
    client.patch(f"{URL}/{d['id']}", json={"exchange_rate": "1350.25"})
    a = client.post(f"{URL}/{d['id']}/approve").json()["data"]
    assert (a["status"], a["krw_goods_total"], a["cost"]["goods_krw"]) == ("APPROVED", 2025, 2025)
    assert client.patch(f"{URL}/{d['id']}", json={"exchange_rate": "1400"}).status_code == 409  # 승인 뒤에는 고칠 수 없다
    log = session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == d["id"], PoChangeLog.field == "krw_goods_total")).one()
    assert (log.old_value, log.new_value) == (None, "2025")


def test_krw_approval_snapshot_without_extra_log(client, world, items, session):
    login_as(client)
    d = create(client, world, krw(items["P1"], 2, 500))
    approve_and_order(client, d["id"])
    assert session.get(PurchaseOrder, d["id"]).krw_goods_total == 1000
    assert not session.scalars(select(PoChangeLog).where(PoChangeLog.field == "krw_goods_total")).all()


# ----- 입고 기준 원가 (마감 수량 제외, 운송비·부대비용은 전액) -----

def test_received_cost_partial_close_and_full(client, world, items):
    login_as(client)
    d = create(client, world, {"product_id": items["BOX"].id, "box_quantity": 2}, freight_amount=500)  # 1,000원 3개입 2박스
    o = approve_and_order(client, d["id"])
    o = receive(client, o, [4])  # 4개 입고 → 4 × 1,000 ÷ 3 = 1,333.33 → 1,333
    assert (o["cost"]["goods_krw"], o["cost"]["received_goods_krw"], o["cost"]["received_total"]) == (2000, 1333, 1833)
    closed = client.post(f"{URL}/{d['id']}/close-remaining", json={"reason": "단종"}).json()["data"]
    assert closed["status"] == "RECEIVED" and closed["cost"]["received_goods_krw"] == 1333  # 마감 수량 2개 제외


def test_fully_received_equals_snapshot(client, world, items):
    login_as(client)
    d = create(client, world, fx(items["P1"], 7, "0.33"), fx(items["BOX"], 2, "10.01", box=True), currency="USD", exchange_rate="1350.45")
    o = approve_and_order(client, d["id"])
    done = receive(client, o, [7, 6])
    assert done["status"] == "RECEIVED"
    # 7 × 0.33 = 2.31, 2박스 × 10.01 = 20.02 → 22.33달러 × 1,350.45 = 30,155.5485 → 30,155원
    assert done["cost"]["received_goods_krw"] == done["krw_goods_total"] == 30155


# ----- 추천·슬랙 초안: 외화 공급업체는 전체 거절 -----

def test_recommendation_draft_rejects_foreign_supplier(client, world, items, session):
    login_as(client)
    client.patch(f"{SUPPLIERS}/{world['a_supplier'].id}", json={"default_currency": "USD"})
    r = client.post("/api/v1/recommendations/drafts", json={"items": [{"product_id": items["P1"].id, "quantity": 5}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FOREIGN_CURRENCY_SUPPLIER"
    assert "A업체" in r.json()["error"]["message"] and "작성 화면에서 직접" in r.json()["error"]["message"]
    assert not session.scalars(select(PurchaseOrder)).all()


def test_recommendation_draft_rejects_existing_foreign_draft(client, world, items):
    login_as(client)
    create(client, world, fx(items["P2"], 1, "1"), currency="USD")  # 원화 업체지만 외화로 작성 중인 초안
    r = client.post("/api/v1/recommendations/drafts", json={"items": [{"product_id": items["P1"].id, "quantity": 5}]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "FOREIGN_CURRENCY_SUPPLIER"


# ----- 외화 문서는 PR 3 전까지 409 (임시 가드) -----

def test_foreign_document_is_blocked_until_pr3(client, world, items):
    login_as(client)
    d = create(client, world, fx(items["P1"], 1, "1"), currency="USD", exchange_rate="1350")
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{d['id']}/approve")
    for path in ("document", "document.xlsx", "email"):
        r = client.get(f"{URL}/{d['id']}/{path}")
        assert r.status_code == 409 and r.json()["error"]["code"] == "FX_DOCUMENT_NOT_READY", path


# ----- 변경 이력·내보내기 -----

def test_change_log_for_cost_fields(client, world, items, session):
    login_as(client)
    d = create(client, world, krw(items["P1"], 1, 1000))
    client.patch(f"{URL}/{d['id']}", json={"freight_amount": 120000, "freight_terms": "FOB", "special_terms": "특약",
                                          "extra_costs": [{"name": "통관 수수료", "amount": 30000}]})
    rows = {r.field: (r.old_value, r.new_value) for r in session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == d["id"]))}
    assert rows["extra_costs"] == (None, "통관 수수료 30,000원")
    assert rows["freight_amount"] == (None, "120000") and rows["freight_terms"] == (None, "FOB") and rows["special_terms"] == (None, "특약")
    client.patch(f"{URL}/{d['id']}", json={"extra_costs": [{"name": "통관 수수료", "amount": 30000}]})  # 같은 값이면 행이 안 생긴다
    assert len(session.scalars(select(PoChangeLog).where(PoChangeLog.field == "extra_costs")).all()) == 1


def test_export_has_cost_columns(client, world, items):
    login_as(client)
    create(client, world, fx(items["P1"], 3, "0.50"), currency="USD", exchange_rate="1350.25", freight_amount=100)
    body = client.get(f"{URL}/export", params={"format": "csv"}).content.decode("utf-8-sig").splitlines()
    head = body[0].split(",")
    row = dict(zip(head, body[1].split(","), strict=True))
    assert (row["통화"], row["환율"], row["품목 원화 합계"], row["원가"], row["외화 단가"], row["외화 금액"], row["단가"]) == (
        "USD", "1350.25", "2025", "2125", "0.50", "1.50", "")


# ----- 마이그레이션 채워 넣기: 승인한 적 있는 발주서만, 완전 입고면 입고 기준 = 스냅샷 -----

def test_backfill_fills_approved_orders_and_matches_received_cost(client, world, items, session):
    login_as(client)
    full = create(client, world, krw(items["P1"], 5, 1001), {"product_id": items["BOX"].id, "box_quantity": 2})
    o = approve_and_order(client, full["id"])
    receive(client, o, [5, 6])  # 완전 입고
    login_as(client)
    sid = client.post(SUPPLIERS, json={"name": "둘째업체", "lead_time_days": 1}).json()["data"]["id"]
    cancelled = client.post(URL, json={"supplier_id": sid, "items": [krw(items["P2"], 1, 700)]}).json()["data"]
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{cancelled['id']}/approve")
    client.post(f"{URL}/{cancelled['id']}/cancel")  # 승인 뒤 취소
    draft = create(client, world, krw(items["P3"], 1, 900))  # 초안 (A업체 DRAFT 는 완전 입고 뒤라 새로 만들 수 있다)

    session.execute(text("ALTER TABLE purchase_orders DROP CONSTRAINT ck_purchase_orders_krw_goods_total"))  # 마이그레이션 직전 상태로 (테스트 끝에 되돌려진다)
    session.execute(text("UPDATE purchase_orders SET krw_goods_total = NULL"))
    spec = importlib.util.spec_from_file_location("migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    session.execute(text(migration.BACKFILL))
    session.execute(text("ALTER TABLE purchase_orders ADD CONSTRAINT ck_purchase_orders_krw_goods_total "
                         "CHECK (approved_at IS NULL OR krw_goods_total IS NOT NULL)"))  # 채운 뒤 제약이 다시 통과한다
    session.expire_all()
    assert session.get(PurchaseOrder, full["id"]).krw_goods_total == 5 * 1001 + 2 * 1000
    assert session.get(PurchaseOrder, cancelled["id"]).krw_goods_total == 700
    assert session.get(PurchaseOrder, draft["id"]).krw_goods_total is None
    got = client.get(f"{URL}/{full['id']}").json()["data"]
    assert got["status"] == "RECEIVED" and got["cost"]["received_goods_krw"] == got["krw_goods_total"] == 7005


# ----- 리뷰 반영: DB 제약과 금액 문자열 모양 -----

def db_rejects(session, sql, **params):
    """SQL 이 CHECK 에 걸리는지 본다. 세이브포인트 안에서 실행해 실패해도 테스트 트랜잭션은 이어진다."""
    try:
        with session.begin_nested():
            session.execute(text(sql), params)
    except IntegrityError:
        return True
    return False


def test_approved_fx_order_keeps_rate_in_db(client, world, items, session):
    login_as(client)
    draft = create(client, world, fx(items["P1"], 1, "1"), currency="USD")  # 작성 중에는 환율이 비어도 된다
    assert not db_rejects(session, "UPDATE purchase_orders SET exchange_rate = NULL WHERE id = :i", i=draft["id"])
    approve_and_order(client, client.patch(f"{URL}/{draft['id']}", json={"exchange_rate": "1350"}).json()["data"]["id"])
    assert db_rejects(session, "UPDATE purchase_orders SET exchange_rate = NULL WHERE id = :i", i=draft["id"])


@pytest.mark.parametrize("currency", list(CURRENCIES))
def test_rate_unit_check_matches_currencies(client, world, items, session, currency):
    """DB CHECK 의 기준 단위가 po_money.CURRENCIES 와 같다: 맞는 단위만 들어가고 다른 단위(1↔100)는 거절."""
    login_as(client)
    d = create(client, world, krw(items["P1"], 1, 1000))
    unit = CURRENCIES[currency][0]
    sql = "UPDATE purchase_orders SET currency = :c, rate_unit = :u WHERE id = :i"
    assert db_rejects(session, sql, c=currency, u=100 if unit == 1 else 1, i=d["id"])  # 예) USD + 100, JPY + 1
    assert not db_rejects(session, sql, c=currency, u=unit, i=d["id"])


@pytest.mark.parametrize("bad", ["1e1", "１２", "-0", " 12", "+1", "1.", "NaN"])
@pytest.mark.parametrize("field", ["fx_price", "exchange_rate"])
def test_money_strings_follow_po_money_rule(client, world, items, field, bad):
    login_as(client)
    line = fx(items["P1"], 1, bad if field == "fx_price" else "1")
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": [line], "currency": "USD",
                               **({"exchange_rate": bad} if field == "exchange_rate" else {})})
    assert r.status_code == 422, r.json()


def test_money_json_numbers_still_allowed(client, world, items):
    login_as(client)
    d = create(client, world, fx(items["P1"], 2, 1.25), currency="USD", exchange_rate=1350)  # 문서대로 JSON 숫자도 받는다
    assert (d["items"][0]["fx_unit_price"], d["exchange_rate"], d["cost"]["goods_krw"]) == ("1.25", "1350.00", 3375)
