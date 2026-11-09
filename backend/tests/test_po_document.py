"""발주서 문서·엑셀(#157): 금액 계산, 한글 금액, 승인 이후만, 회사 분리, 회사 정보가 비어도 출력, 지불조건·납품장소."""

from io import BytesIO  # 엑셀 응답을 메모리에서 읽는다

import pytest  # 테스트 도구
from openpyxl import load_workbook  # 엑셀 읽기

from app.services.po_document import korean_amount, vat_of  # 순수 함수
from tests.helpers import login_as  # 공통 로그인
from tests.test_purchase_orders import add_product, body, line  # 발주 테스트의 준비 도구

URL = "/api/v1/purchase-orders"  # 발주 경로


@pytest.mark.parametrize(("amount", "text"), [
    (0, "영"),
    (1, "일"),
    (10, "일십"),
    (1_000, "일천"),
    (10_000, "일만"),
    (836_000, "팔십삼만육천"),  # 목업의 합계
    (1_105, "일천일백오"),
    (100_000_000, "일억"),  # 0000 묶음은 건너뛴다
    (1_0000_0001, "일억일"),
    (123_456_789, "일억이천삼백사십오만육천칠백팔십구"),
])
def test_korean_amount(amount, text):
    assert korean_amount(amount) == text


def test_vat_drops_fraction():
    # 공급가액 1,005원 → 부가세 100.5원 → 100원 (원 미만 버림), 합계 1,105원
    assert vat_of(1_005) == 100 and vat_of(760_000) == 76_000 and vat_of(9) == 0


def make_order(client, session, world, approve=True, **fields):
    """회사 A 관리자로 로그인해 발주서를 만들고(선택: 승인) → (발주 응답, 품목)."""
    p1 = add_product(session, world, "a", "P1")
    p2 = add_product(session, world, "a", "P2")
    session.commit()
    login_as(client, "admin@a.test")
    response = client.post(URL, json=body(world, line(p1, 55, 8000), line(p2, 40, 6500), **fields))
    assert response.status_code == 201, response.json()
    order = response.json()["data"]
    if approve:
        assert client.post(f"{URL}/{order['id']}/approve").status_code == 200
    return order, (p1, p2)


def test_document_amounts_and_company_fallbacks(client, session, world):
    company = world["a_company"]
    company.business_number, company.representative = "1234567890", "홍길동"
    company.phone, company.address = "02-555-0100", "서울시 성동구 아차산로 00"
    world["a_supplier"].contact_name, world["a_supplier"].payment_terms = "박영수", "납품 후 월말 현금"
    session.commit()
    order, _ = make_order(client, session, world)

    doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
    assert [(l["quantity"], l["unit_price"], l["amount"]) for l in doc["lines"]] == [(55, 8000, 440_000), (40, 6500, 260_000)]
    # 공급가액 700,000 → 부가세 70,000 → 합계 770,000 (줄별 세액 없이 합계에 한 번)
    assert (doc["supply_total"], doc["vat"], doc["total"]) == (700_000, 70_000, 770_000)
    assert doc["total_korean"] == "칠십칠만"
    assert doc["supplier"]["contact_name"] == "박영수"
    assert doc["buyer"]["business_number"] == "1234567890" and doc["buyer"]["author_name"] == "a-ADMIN"
    assert doc["payment_terms"] == "납품 후 월말 현금"  # 공급업체 기본값이 복사돼 있다
    assert doc["delivery_address"] == "서울시 성동구 아차산로 00"  # 납품장소를 안 적으면 회사 주소


def test_document_box_line(client, session, world):
    p = add_product(session, world, "a", "BX", units_per_box=24, box_unit_cost=12_000)
    session.commit()
    login_as(client, "admin@a.test")
    response = client.post(URL, json={"supplier_id": world["a_supplier"].id, "items": [{"product_id": p.id, "box_quantity": 5}]})
    order = response.json()["data"]
    client.post(f"{URL}/{order['id']}/approve")
    [item] = client.get(f"{URL}/{order['id']}/document").json()["data"]["lines"]
    assert (item["unit"], item["quantity"], item["unit_price"], item["amount"], item["note"]) == ("박스", 5, 12_000, 60_000, "1박스=24개")


def test_document_with_empty_company_info(client, session, world):
    order, _ = make_order(client, session, world)  # 회사 정보·지불조건·납품장소 모두 비어 있다
    doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
    assert doc["buyer"]["business_number"] is None and doc["delivery_address"] is None and doc["payment_terms"] is None
    assert client.get(f"{URL}/{order['id']}/document.xlsx").status_code == 200


def test_document_only_after_approval(client, session, world):
    order, _ = make_order(client, session, world, approve=False)
    assert client.get(f"{URL}/{order['id']}/document").status_code == 409  # DRAFT
    client.post(f"{URL}/{order['id']}/approve")
    assert client.get(f"{URL}/{order['id']}/document").status_code == 200  # APPROVED
    client.post(f"{URL}/{order['id']}/cancel")
    assert client.get(f"{URL}/{order['id']}/document").status_code == 409  # CANCELLED
    assert client.get(f"{URL}/{order['id']}/document.xlsx").status_code == 409


def test_document_other_company_and_anonymous(client, session, world):
    order, _ = make_order(client, session, world)
    login_as(client, "admin@b.test")
    for suffix in ("document", "document.xlsx"):
        assert client.get(f"{URL}/{order['id']}/{suffix}").status_code == 404  # 다른 회사 발주서는 열리지 않는다
    client.post("/api/v1/auth/logout")
    assert client.get(f"{URL}/{order['id']}/document").status_code == 401


def test_xlsx_matches_document(client, session, world):
    world["a_company"].business_number = "1234567890"
    session.commit()
    order, _ = make_order(client, session, world)
    doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
    response = client.get(f"{URL}/{order['id']}/document.xlsx")
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert order["po_number"] in response.headers["content-disposition"]
    rows = [[c for c in row] for row in load_workbook(BytesIO(response.content)).active.iter_rows(values_only=True)]
    flat = [cell for row in rows for cell in row]
    for expected in ("123-45-67890", f"합계금액: 일금 {doc['total_korean']} 원정 (₩{doc['total']:,}, 부가세 포함)"):
        assert expected in flat
    assert [r[3:6] for r in rows if r[0] in (1, 2)] == [[l["quantity"], l["unit_price"], l["amount"]] for l in doc["lines"]]
    totals = {r[4]: r[5] for r in rows if r[4] in ("공급가액 합계", "부가세 (10%)", "합계")}
    assert totals == {"공급가액 합계": doc["supply_total"], "부가세 (10%)": doc["vat"], "합계": doc["total"]}


def test_payment_terms_and_delivery_address_on_order(client, session, world):
    world["a_supplier"].payment_terms = "월말 현금"
    session.commit()
    # 안 보내면 공급업체 기본값을 복사, 보내면 그 값
    order, _ = make_order(client, session, world, approve=False)
    assert order["payment_terms"] == "월말 현금" and order["delivery_address"] is None
    url = f"{URL}/{order['id']}"
    response = client.patch(url, json={"payment_terms": "선금 50%", "delivery_address": "물류창고"})
    assert response.json()["data"]["payment_terms"] == "선금 50%"
    assert response.json()["data"]["delivery_address"] == "물류창고"
    # 공급업체 기본값을 나중에 바꿔도 이미 복사된 값은 그대로, null·빈 글자는 비우기
    assert client.patch(url, json={"payment_terms": None, "delivery_address": ""}).json()["data"]["payment_terms"] is None
    assert client.get(url).json()["data"]["delivery_address"] is None
    assert client.patch(url, json={"payment_terms": "x" * 201}).status_code == 422  # 200자까지
