"""매입 세금계산서 수취 기록과 입고 금액 대조 (#268): /purchase-orders/{id}/tax-invoices.

준비 발주서는 test_po_transitions.make_po (P1 100개 × 800원). 입고 금액 = 누적 입고량 × 800원.
대조 = 받은 공급가액 합(취소 제외) − 입고 금액. MISSING(입고 있음·계산서 0장) / MATCHED(차이 0) / DIFFERENT.
"""

from datetime import timedelta  # 미래 발행일
from io import BytesIO  # 엑셀 바이트 읽기

import pytest  # 테스트 도구
from openpyxl import load_workbook  # 엑셀 글자 읽기

from app.clock import seoul_today  # 서울 오늘
from app.config import settings  # FX 스위치
from app.errors import AppError  # 동시 요청의 409
from app.models import Product, PurchaseOrder, Supplier  # 준비 데이터
from app.schemas.purchase_orders import TaxInvoiceCreate  # 서비스 직접 호출용 본문
from app.services import supplier_reply, tax_invoices  # 공개 확인 화면, 대상 서비스
from tests.concurrency import (  # 진짜 commit 하는 동시 요청 도구
    ordered_po,
    run_at_once,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_allowed_actions import correct, latest_receipt_id  # 입고 정정 도구
from tests.test_po_transitions import (  # P1 발주서 만들기·입고 (읽기만)
    URL,
    make_po,
    outbox,  # noqa: F401 (메일 미리보기용 가짜 메일 서버 픽스처)
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
    receive,
)

TODAY = seoul_today().isoformat()


def body(number="INV-1", supply=10_000, tax=1_000, **extra):
    return {"invoice_number": number, "issue_date": TODAY, "supply_amount": supply, "tax_amount": tax, **extra}


def post(client, po, **kw):
    return client.post(f"{URL}/{po['id']}/tax-invoices", json=body(**kw))


def view(client, po):
    r = client.get(f"{URL}/{po['id']}/tax-invoices")
    assert r.status_code == 200, r.json()
    return r.json()["data"]


def cancel(client, po, invoice_id, reason="번호 오입력"):
    return client.post(f"{URL}/{po['id']}/tax-invoices/{invoice_id}/cancel",
                       json={} if reason is None else {"reason": reason})


def code(r):
    return r.status_code, r.json()["error"]["code"]


# ----- 합계와 대조 -----
def test_partial_receipt_sum_and_status(client, world, product):  # noqa: F811
    """60개 입고(48,000원): 계산서 0장 MISSING → 30,000 DIFFERENT(−18,000) → +18,000 MATCHED. 담당자가 기록한다."""
    po = make_po(client, world, product, "ORDERED", received=60)
    login_as(client)  # 담당자
    s = view(client, po)["summary"]
    assert s == {"received_goods_krw": 48_000, "supply_total": 0, "tax_total": 0, "difference": -48_000,
                 "status": "MISSING", "line_count": 1}

    r = post(client, po, number="INV-1", supply=30_000, tax=3_000)
    assert r.status_code == 201, r.json()
    s = r.json()["data"]["summary"]
    assert (s["supply_total"], s["difference"], s["status"]) == (30_000, -18_000, "DIFFERENT")  # 덜 받음

    out = post(client, po, number="INV-2", supply=18_000, tax=1_801, memo="2차분").json()["data"]
    assert out["summary"] == {"received_goods_krw": 48_000, "supply_total": 48_000, "tax_total": 4_801,
                                   "difference": 0, "status": "MATCHED", "line_count": 1}
    latest = out["items"][0]  # 최신순
    assert (latest["invoice_number"], latest["total"], latest["tax_expected"], latest["memo"]) == ("INV-2", 19_801, 1_800, "2차분")
    assert latest["created_by_name"] == "a-STAFF" and latest["cancelled_at"] is None  # 세액이 10% 와 달라도 저장된다


def test_receipt_correction_changes_difference(client, world, product):  # noqa: F811
    """60개 입고 + 48,000 계산서 MATCHED → 입고 10개 정정 → 입고 금액 40,000, 차이 +8,000(더 받음). 계산서는 그대로."""
    po = make_po(client, world, product, "ORDERED", received=60)
    post(client, po, supply=48_000, tax=4_800)
    assert view(client, po)["summary"]["status"] == "MATCHED"
    correct(client, latest_receipt_id(client), 10)
    s = view(client, po)["summary"]
    assert (s["received_goods_krw"], s["supply_total"], s["difference"], s["status"]) == (40_000, 48_000, 8_000, "DIFFERENT")


def test_box_line_partial_receipt_matches_floor(client, world, session):
    """1,000원 3개입 박스 2박스 중 4개 입고 → 4 × 1,000 ÷ 3 = 1,333.33 → 1,333원. 계산서 1,333 이면 MATCHED."""
    box = Product(company_id=world["a_company"].id, sku="BOX", name="박스품목", unit="개", unit_cost=1000,
                  default_supplier_id=world["a_supplier"].id, units_per_box=3, box_unit_cost=1000, order_unit="박스")
    session.add(box)
    session.commit()
    login_as(client)
    po = client.post(URL, json={"supplier_id": world["a_supplier"].id,
                                "items": [{"product_id": box.id, "box_quantity": 2}]}).json()["data"]
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{po['id']}/approve")
    client.post(f"{URL}/{po['id']}/order")
    assert receive(client, po, 4).status_code == 201
    out = post(client, po, supply=1_333, tax=133).json()["data"]
    assert (out["summary"]["received_goods_krw"], out["summary"]["status"]) == (1_333, "MATCHED")


def test_no_receipt_with_invoice_is_different(client, world, product):  # noqa: F811
    """입고 0건: 계산서도 없으면 0 = 0 이라 MATCHED(입고된 줄 0), 계산서를 먼저 받으면 DIFFERENT(+10,000)."""
    po = make_po(client, world, product, "ORDERED")
    s = view(client, po)["summary"]
    assert (s["received_goods_krw"], s["status"], s["line_count"]) == (0, "MATCHED", 0)
    s = post(client, po).json()["data"]["summary"]
    assert (s["difference"], s["status"]) == (10_000, "DIFFERENT")


def test_close_remaining_uses_received_only(client, world, product):  # noqa: F811
    """95개 입고 후 잔량 마감(RECEIVED): 입고 금액은 95 × 800 = 76,000(마감 5개 제외). 입고 완료 발주에도 기록된다."""
    po = make_po(client, world, product, "ORDERED", received=95)
    assert client.post(f"{URL}/{po['id']}/close-remaining", json={"reason": "단종"}).status_code == 200
    r = post(client, po, supply=76_000, tax=7_600)
    assert r.status_code == 201, r.json()
    assert r.json()["data"]["summary"]["status"] == "MATCHED"


# ----- 번호 중복 -----
def test_duplicate_number_rules(client, world, product, session):  # noqa: F811
    """같은 회사·같은 업체의 유효한 같은 번호는 409(앞뒤 공백 무시), 다른 업체는 허용, 취소한 번호는 다시 넣을 수 있다."""
    po1 = make_po(client, world, product, "ORDERED")
    po2 = make_po(client, world, product, "ORDERED")  # 같은 A업체의 다른 발주서
    first = post(client, po1, number="INV-9").json()["data"]["items"][0]
    assert code(post(client, po2, number="  INV-9 ")) == (409, "DUPLICATE_TAX_INVOICE")

    other = Supplier(company_id=world["a_company"].id, name="A2업체", lead_time_days=3)  # 같은 회사의 다른 업체
    session.add(other)
    session.flush()
    p2 = Product(company_id=world["a_company"].id, sku="P2", name="품목2", unit="개", unit_cost=500, default_supplier_id=other.id)
    session.add(p2)
    session.commit()
    login_as(client)
    po3 = client.post(URL, json={"supplier_id": other.id, "items": [{"product_id": p2.id, "quantity": 10, "unit_price": 500}]}).json()["data"]
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{po3['id']}/approve")
    client.post(f"{URL}/{po3['id']}/order")
    assert post(client, po3, number="INV-9").status_code == 201  # 업체가 다르면 같은 번호 허용

    assert cancel(client, po1, first["id"]).status_code == 200
    assert post(client, po2, number="INV-9").status_code == 201  # 취소한 번호는 다시 넣을 수 있다


def test_concurrent_same_number_only_one_succeeds(engine, committed_company):
    """서로 다른 발주서 두 장에 같은 번호를 동시에 넣으면 하나만 성공하고 하나는 409 (부분 유일 인덱스)."""
    data = committed_company
    po_a, _ = ordered_po(engine, data, [data["product_id"]])
    po_b, _ = ordered_po(engine, data, [data["product_id"]])
    request = TaxInvoiceCreate(invoice_number="SAME-1", issue_date=seoul_today(), supply_amount=100, tax_amount=10)

    def record(order_id):
        return lambda: run_in_new_session(engine, lambda s: tax_invoices.record(data["company_id"], s, data["admin_id"], order_id, request))

    results = run_at_once(record(po_a), record(po_b))
    errors = [r for r in results if isinstance(r, AppError)]
    assert len(errors) == 1 and errors[0].code == "DUPLICATE_TAX_INVOICE", results
    assert sum(isinstance(r, dict) for r in results) == 1


# ----- 취소 -----
def test_cancel_rules(client, world, product):  # noqa: F811
    """사유 필수(빈칸·공백 422), 취소하면 합계에서 빠지고 목록에는 남는다, 두 번 취소는 409."""
    po = make_po(client, world, product, "ORDERED", received=10)  # 8,000원
    inv = post(client, po, supply=8_000, tax=800).json()["data"]["items"][0]
    assert cancel(client, po, inv["id"], reason=None).status_code == 422
    assert code(cancel(client, po, inv["id"], reason="   ")) == (422, "VALIDATION_ERROR")

    login_as(client)  # 담당자도 취소할 수 있다
    out = cancel(client, po, inv["id"]).json()["data"]
    row = out["items"][0]
    assert (row["cancel_reason"], row["cancelled_by_name"]) == ("번호 오입력", "a-STAFF") and row["cancelled_at"]
    assert (out["summary"]["supply_total"], out["summary"]["status"]) == (0, "MISSING")
    assert code(cancel(client, po, inv["id"])) == (409, "ALREADY_CANCELLED")


def test_cancel_allowed_on_cancelled_order(client, world, product):  # noqa: F811
    """입고 전 발주함에 기록 → 발주서 취소 → 새 기록은 409, 계산서 취소는 된다."""
    po = make_po(client, world, product, "ORDERED")
    inv = post(client, po).json()["data"]["items"][0]
    assert client.post(f"{URL}/{po['id']}/cancel", json={"reason": "업체 사정"}).status_code == 200
    assert code(post(client, po, number="INV-2")) == (409, "INVALID_STATUS")
    assert view(client, po)["summary"]["difference"] == 10_000  # 취소된 발주의 입고 금액은 0
    assert cancel(client, po, inv["id"]).status_code == 200


# ----- 막히는 입력 -----
@pytest.mark.parametrize("state", ["DRAFT", "APPROVED", "CANCELLED"])
def test_record_blocked_by_order_status(client, world, product, state):  # noqa: F811
    po = make_po(client, world, product, state)
    assert code(post(client, po)) == (409, "INVALID_STATUS")


def test_foreign_currency_order_is_422(client, world, product, monkeypatch):  # noqa: F811
    monkeypatch.setattr(settings, "fx_enabled", True)  # 외화 발주서를 만들 때만 켠다
    login_as(client)
    po = client.post(URL, json={"supplier_id": world["a_supplier"].id, "currency": "USD", "exchange_rate": "1350",
                                "items": [{"product_id": product.id, "quantity": 1, "fx_price": "1"}]}).json()["data"]
    login_as(client, "admin@a.test")
    client.post(f"{URL}/{po['id']}/approve")
    assert client.post(f"{URL}/{po['id']}/order").json()["data"]["status"] == "ORDERED"
    r = post(client, po)
    assert code(r) == (422, "VALIDATION_ERROR") and r.json()["error"]["details"][0]["field"] == "currency"


@pytest.mark.parametrize("bad", [
    {"supply_amount": -1}, {"tax_amount": -1}, {"supply_amount": 1.5},  # 음수·소수
    {"issue_date": (seoul_today() + timedelta(days=1)).isoformat()},  # 미래 발행일
    {"issue_date": "2000-01-01"},  # 5년보다 이른 날짜
    {"invoice_number": "   "}, {"invoice_number": "x" * 51},  # 빈 번호·51자
    {"supplier_id": 1}, {"company_id": 1},  # 업체·회사는 본문으로 받지 않는다
])
def test_invalid_input_is_422(client, world, product, bad):  # noqa: F811
    po = make_po(client, world, product, "ORDERED")
    r = client.post(f"{URL}/{po['id']}/tax-invoices", json=body() | bad)
    assert code(r) == (422, "VALIDATION_ERROR")


def test_other_company_is_404(client, world, product):  # noqa: F811
    """회사 B 관리자는 회사 A 발주서의 조회·기록·취소가 모두 404. 다른 발주서의 계산서 id 도 404."""
    po = make_po(client, world, product, "ORDERED")
    inv = post(client, po).json()["data"]["items"][0]
    other_po = make_po(client, world, product, "ORDERED")
    assert code(cancel(client, other_po, inv["id"])) == (404, "NOT_FOUND")  # 같은 회사라도 다른 발주서의 계산서
    login_as(client, "admin@b.test")
    assert client.get(f"{URL}/{po['id']}/tax-invoices").status_code == 404
    assert code(post(client, po, number="B-1")) == (404, "NOT_FOUND")
    assert code(cancel(client, po, inv["id"])) == (404, "NOT_FOUND")


# ----- 목록 필터 -----
def test_missing_filter_and_status_counts_agree(client, world, product):  # noqa: F811
    """미수취 = 입고 기록 있음 + 유효 계산서 0장. 계산서 있음·입고 없음은 빠지고, 취소한 계산서만 있으면 다시 미수취."""
    missing = make_po(client, world, product, "ORDERED", received=10)
    has_invoice = make_po(client, world, product, "ORDERED", received=10)
    post(client, has_invoice, number="H-1")
    make_po(client, world, product, "ORDERED")  # 입고 없음
    cancelled = make_po(client, world, product, "RECEIVED")
    inv = post(client, cancelled, number="C-1").json()["data"]["items"][0]
    cancel(client, cancelled, inv["id"])

    r = client.get(URL, params={"tax_invoice": "missing"}).json()
    assert {o["id"] for o in r["data"]} == {missing["id"], cancelled["id"]}
    counts = client.get(f"{URL}/status-counts", params={"tax_invoice": "missing"}).json()["data"]
    assert sum(counts.values()) == r["meta"]["total"] == 2 and (counts["ORDERED"], counts["RECEIVED"]) == (1, 1)
    assert client.get(URL, params={"tax_invoice": "other"}).status_code == 422
    assert "tax_invoices" not in r["data"][0]  # 목록 응답에는 계산서 정보가 없다


# ----- 공급업체 출력에 나가지 않는다 -----
def test_tax_invoice_never_reaches_supplier_outputs(client, world, product, session, outbox):  # noqa: F811
    """표식 번호·메모로 기록한 뒤 문서·엑셀·메일 미리보기·공개 확인 화면·발주서 응답 어디에도 표식이 없다."""
    secrets = ("SECRET-TAX-268", "SECRET-TAX-MEMO-268", "4321987", "4,321,987")
    po = make_po(client, world, product, "ORDERED", received=10)
    assert post(client, po, number=secrets[0], supply=4_321_987, tax=0, memo=secrets[1]).status_code == 201

    doc = client.get(f"{URL}/{po['id']}/document")
    xlsx = client.get(f"{URL}/{po['id']}/document.xlsx")
    mail = client.get(f"{URL}/{po['id']}/email")
    assert doc.status_code == xlsx.status_code == mail.status_code == 200
    sheet = load_workbook(BytesIO(xlsx.content)).active
    outputs = {
        "document": doc.text,
        "xlsx": "\n".join(str(c.value) for row in sheet.iter_rows() for c in row if c.value is not None),
        "mail": mail.text,
        "public_view": str(supplier_reply.public_view(session, session.get(PurchaseOrder, po["id"]))),
        "detail": client.get(f"{URL}/{po['id']}").text,
    }
    for name, text in outputs.items():
        for secret in secrets:
            assert secret not in text, f"세금계산서 값 {secret!r} 이 {name} 출력에 들어갔습니다"
