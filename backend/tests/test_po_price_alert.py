"""발주 단가 변동 경고 테스트 (#283): 순수 함수 표 테스트 + POST /purchase-orders/price-check 서버 테스트."""

from datetime import UTC, datetime, timedelta  # 승인 시각
from fractions import Fraction  # 직전 가격(분수)

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 행 수 세기

from app.config import settings  # 임계값 설정
from app.models import Company, PoChangeLog, Product, PurchaseOrder, PurchaseOrderItem, Supplier
from app.schemas.common import MAX_ORDER_LINES  # 발주서 줄 수 상한
from app.services.price_alert import price_alert
from tests.helpers import login_as
from tests.test_po_transitions import (  # P1 발주서 만들기 (읽기만)
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
)

CHECK = f"{URL}/price-check"
T0 = datetime(2026, 10, 2, 3, 0, tzinfo=UTC)  # 서울 2026-10-02 12:00


# ----- 순수 함수 표 (임계 10%) -----
@pytest.mark.parametrize("new, previous, expected", [
    (1100, Fraction(1000), ("UP", 10)),       # 정확히 10% 는 경고 (이상)
    (1099, Fraction(1000), None),             # 9.9% 는 경고 없음
    (900, Fraction(1000), ("DOWN", 10)),      # 하락도 정확히 10% 는 경고
    (901, Fraction(1000), None),
    (1000, Fraction(1000), None),             # 같은 값
    (1250, Fraction(1000), ("UP", 25)),
    (0, Fraction(1000), ("ZERO", 100)),       # 입력 0원
    (None, Fraction(1000), None),             # 입력 비어 있음은 0 이 아니다
    (100, Fraction(0), None),                 # 직전 0원이면 퍼센트를 낼 수 없다
    (4, Fraction(3), ("UP", 33)),             # 33.3% 내림
    (221, Fraction(200), ("UP", 10)),         # 10.5% 내림
    (1, Fraction(1000), ("DOWN", 99)),        # 99.9% 내림 (0원이 아니면 "100% 낮음"이 되지 않는다)
    (600, Fraction(5000, 10), ("UP", 20)),    # 직전이 박스 5,000원 ÷ 10개 = 500원
])
def test_price_alert_table(new, previous, expected):
    assert price_alert(new, previous, 10) == expected


def test_price_alert_no_previous_and_threshold():
    assert price_alert(2000, None, 10) is None  # 직전 발주 없음
    assert price_alert(1050, Fraction(1000), 5) == ("UP", 5)  # 임계값을 바꾸면 경계가 따라 움직인다
    assert price_alert(1050, Fraction(1000), 10) is None


# ----- 준비 도구 -----
_seq = iter(range(1, 10_000))


def add_po(session, company_id, user_id, supplier_id, product_id, price, status="APPROVED", approved_at=T0,
           currency="KRW", box=None):
    """발주서 한 장(줄 하나)을 직접 넣는다. box=(입수, 박스단가)면 박스 줄. 외화면 fx 단가 줄."""
    fx = currency != "KRW"
    order = PurchaseOrder(
        company_id=company_id, supplier_id=supplier_id, po_number=f"PO-TEST-{next(_seq):03d}", status=status,
        created_by=user_id, currency=currency, rate_unit=1, exchange_rate=1300 if fx else None,
        approved_at=approved_at if status != "DRAFT" else None, krw_goods_total=0 if status != "DRAFT" else None,
    )
    session.add(order)
    session.flush()
    line = {"unit_price": None, "fx_unit_price": price} if fx else {"unit_price": price, "fx_unit_price": None}
    if box is not None:
        line.update(units_per_box=box[0], box_unit_price=box[1], order_unit="박스", quantity=box[0] * 10)
    else:
        line.update(quantity=10)
    session.add(PurchaseOrderItem(company_id=company_id, purchase_order_id=order.id, product_id=product_id, **line))
    session.commit()
    return order


@pytest.fixture
def ctx(world, product, session):  # noqa: F811
    """회사 A 의 공급업체·품목·담당자 번호와 로그인."""
    return world["a_company"].id, world["a_staff"].id, world["a_supplier"].id, product.id


def ask(client, supplier_id, items):
    return client.post(CHECK, json={"supplier_id": supplier_id, "items": items})


def alert_of(client, supplier_id, product_id, price):
    r = ask(client, supplier_id, [{"product_id": product_id, "unit_price": price}])
    assert r.status_code == 200, r.json()
    return r.json()["data"][0]["alert"]


# ----- 직전 발주 찾기 -----
def test_no_previous_order_means_no_alert(client, ctx):
    login_as(client)
    _, _, sup, pid = ctx
    assert alert_of(client, sup, pid, 99999) is None


def test_alert_has_sentence_with_po_number_and_date(client, session, ctx):
    cid, uid, sup, pid = ctx
    po = add_po(session, cid, uid, sup, pid, 1000)
    login_as(client)
    a = alert_of(client, sup, pid, 1250)
    assert a["direction"] == "UP" and a["percent"] == 25 and a["previous_unit_price"] == 1000
    assert a["po_id"] == po.id and a["po_number"] == po.po_number and a["approved_on"] == "2026-10-02"
    assert a["message"] == f"지난번 1,000원보다 25% 높습니다 ({po.po_number}, 10/02)"
    assert alert_of(client, sup, pid, 900)["message"] == f"지난번 1,000원보다 10% 낮습니다 ({po.po_number}, 10/02)"
    assert alert_of(client, sup, pid, 0)["message"] == f"단가가 0원입니다 (지난번 1,000원, {po.po_number}, 10/02)"
    assert alert_of(client, sup, pid, 1099) is None


@pytest.mark.parametrize("status", ["DRAFT", "CANCELLED"])
def test_draft_and_cancelled_are_excluded(client, session, ctx, status):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000, status=status)  # 승인 뒤 취소(approved_at 있음)도 제외
    login_as(client)
    assert alert_of(client, sup, pid, 5000) is None


@pytest.mark.parametrize("status", ["APPROVED", "ORDERED", "RECEIVED"])
def test_approved_and_later_states_are_compared(client, session, ctx, status):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000, status=status)
    login_as(client)
    assert alert_of(client, sup, pid, 1500)["percent"] == 50


def test_other_supplier_and_other_product_are_excluded(client, session, world, ctx):
    cid, uid, sup, pid = ctx
    other_sup = Supplier(company_id=cid, name="다른업체", lead_time_days=3)
    other_product = Product(company_id=cid, sku="P2", name="품목2", unit="개", unit_cost=1000, default_supplier_id=sup)
    session.add_all([other_sup, other_product])
    session.commit()
    add_po(session, cid, uid, other_sup.id, pid, 1000)  # 같은 품목, 다른 공급업체
    add_po(session, cid, uid, sup, other_product.id, 1000)  # 같은 공급업체, 다른 품목
    login_as(client)
    assert alert_of(client, sup, pid, 5000) is None
    assert alert_of(client, other_sup.id, other_product.id, 5000) is None


def test_foreign_currency_order_is_excluded(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000, currency="KRW", approved_at=T0)
    add_po(session, cid, uid, sup, pid, 7, currency="USD", approved_at=T0 + timedelta(days=5))  # 더 최근이지만 외화
    login_as(client)
    assert alert_of(client, sup, pid, 1250)["previous_unit_price"] == 1000  # 외화를 건너뛰고 원화 발주와 비교


def test_latest_approval_wins_and_ties_use_larger_id(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 2000, approved_at=T0 - timedelta(days=30))
    add_po(session, cid, uid, sup, pid, 1000, approved_at=T0)
    login_as(client)
    assert alert_of(client, sup, pid, 1250)["previous_unit_price"] == 1000  # 오래된 2,000원이 아니라 최근 1,000원
    later = add_po(session, cid, uid, sup, pid, 1250, approved_at=T0)  # 같은 시각이면 번호가 큰 발주서
    assert alert_of(client, sup, pid, 1500)["po_id"] == later.id


def test_previous_box_line_is_converted_per_unit(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 999, box=(10, 5000))  # 박스 5,000원 ÷ 10개 = 개당 500원 (줄의 unit_price 999 는 쓰지 않는다)
    login_as(client)
    a = alert_of(client, sup, pid, 600)
    assert a["direction"] == "UP" and a["percent"] == 20 and a["previous_unit_price"] == 500
    assert alert_of(client, sup, pid, 549) is None  # 9.8%


def test_previous_zero_price_or_blank_input_gives_no_alert(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 0)
    login_as(client)
    assert alert_of(client, sup, pid, 100) is None  # 직전 0원은 퍼센트를 낼 수 없다
    assert alert_of(client, sup, pid, None) is None  # 빈 값


def test_threshold_follows_setting(client, session, ctx, monkeypatch):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000)
    login_as(client)
    assert alert_of(client, sup, pid, 1050) is None
    monkeypatch.setattr(settings, "price_alert_percent", 5)
    assert alert_of(client, sup, pid, 1050)["percent"] == 5


def test_many_lines_in_one_request(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000)
    login_as(client)
    r = ask(client, sup, [{"product_id": pid, "unit_price": 1500}, {"product_id": pid, "unit_price": 1001}, {"product_id": pid}])
    out = r.json()["data"]
    assert [row["alert"] is not None for row in out] == [True, False, False]
    assert [row["unit_price"] for row in out] == [1500, 1001, None]  # 보낸 단가를 되돌려 준다


# ----- 회사 분리·권한·입력 검사 -----
def test_tenant_isolation(client, session, world, ctx):
    _, _, sup, pid = ctx
    b_product = Product(company_id=world["b_company"].id, sku="B1", name="B품목", unit="개", unit_cost=1000,
                        default_supplier_id=world["b_supplier"].id)
    session.add(b_product)
    session.commit()
    add_po(session, world["b_company"].id, world["b_staff"].id, world["b_supplier"].id, b_product.id, 1000)
    login_as(client)  # 회사 A
    assert ask(client, world["b_supplier"].id, [{"product_id": b_product.id, "unit_price": 5000}]).status_code == 404  # 다른 회사 공급업체
    assert alert_of(client, sup, b_product.id, 5000) is None  # 다른 회사 품목은 찾지 못한다
    assert alert_of(client, sup, pid, 5000) is None


@pytest.mark.parametrize("email", ["staff@a.test", "admin@a.test"])
def test_both_roles_and_login_required(client, session, ctx, email):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000)
    assert ask(client, sup, [{"product_id": pid, "unit_price": 1500}]).status_code == 401  # 로그인 전
    login_as(client, email)
    assert alert_of(client, sup, pid, 1500) is not None


def test_request_validation(client, ctx):
    login_as(client)
    _, _, sup, pid = ctx
    assert ask(client, sup, []).status_code == 422  # 줄 0개
    assert ask(client, sup, [{"product_id": pid, "unit_price": -1}]).status_code == 422
    assert ask(client, sup, [{"product_id": pid, "unit_price": "abc"}]).status_code == 422
    assert client.post(CHECK, json={"supplier_id": sup, "items": [{"product_id": pid}], "company_id": 2}).status_code == 422  # 회사는 본문으로 못 정한다
    assert ask(client, 987654, [{"product_id": pid}]).status_code == 404


def test_line_limit_equals_order_line_limit(client, ctx):
    login_as(client)
    _, _, sup, pid = ctx
    assert MAX_ORDER_LINES == 2000
    assert ask(client, sup, [{"product_id": pid}] * MAX_ORDER_LINES).status_code == 200
    assert ask(client, sup, [{"product_id": pid}] * (MAX_ORDER_LINES + 1)).status_code == 422


def test_check_changes_nothing(client, session, ctx):
    cid, uid, sup, pid = ctx
    add_po(session, cid, uid, sup, pid, 1000)
    login_as(client)
    before = (session.scalar(select(func.count()).select_from(PurchaseOrder)),
              session.scalar(select(func.count()).select_from(PoChangeLog)),
              session.scalar(select(func.count()).select_from(Company)))
    alert_of(client, sup, pid, 5000)
    after = (session.scalar(select(func.count()).select_from(PurchaseOrder)),
             session.scalar(select(func.count()).select_from(PoChangeLog)),
             session.scalar(select(func.count()).select_from(Company)))
    assert before == after


# ----- 막지 않는다 / 새지 않는다 -----
def test_alert_never_blocks_save_or_approval_and_never_leaks(client, world, product):  # noqa: F811
    first = make_po(client, world, product, "APPROVED")  # 단가 800 으로 승인된 발주
    assert first["status"] == "APPROVED"
    login_as(client)
    # 승인 발주는 DRAFT 가 아니라 같은 공급업체에 새 초안을 만들 수 있다. 단가 9배 → 경고 대상
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id,
                               "items": [{"product_id": product.id, "quantity": 5, "unit_price": 8000}]})
    assert r.status_code == 201, r.json()
    draft = r.json()["data"]
    assert alert_of(client, world["a_supplier"].id, product.id, 8000)["direction"] == "UP"
    r = client.patch(f"{URL}/{draft['id']}", json={"items": [{"product_id": product.id, "quantity": 5, "unit_price": 9000}]})
    assert r.status_code == 200, r.json()  # 저장은 막지 않는다
    for text in (r.text, client.get(f"{URL}/{draft['id']}").text, client.get(URL).text):
        assert "alert" not in text and "price-check" not in text and "지난번" not in text  # 발주서 응답에 경고가 새지 않는다
    login_as(client, "admin@a.test")
    r = client.post(f"{URL}/{draft['id']}/approve")
    assert r.status_code == 200 and r.json()["data"]["status"] == "APPROVED"  # 승인도 막지 않는다
    r = client.get(f"{URL}/{draft['id']}/document")
    assert r.status_code == 200 and "지난번" not in r.text and "alert" not in r.text  # 공급업체용 문서에도 없다
