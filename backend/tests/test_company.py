"""회사 정보 API (#156) 테스트: 관리자 저장·수정, 담당자 읽기만, 회사 분리, 빈 값, 사업자번호 형식."""

import pytest

from tests.helpers import login_as

URL = "/api/v1/company"
FULL = {"business_number": "123-45-67890", "representative": "홍길동", "address": "서울 중구 1", "phone": "02-123-4567"}


def test_admin_saves_and_updates(client, world):
    """관리자 저장 → 조회 → 일부만 수정(나머지 유지). 하이픈은 지우고 숫자 10자리로 저장."""
    login_as(client, "admin@a.test")
    saved = client.patch(URL, json=FULL)
    assert saved.status_code == 200
    assert saved.json()["data"]["business_number"] == "1234567890"
    assert client.patch(URL, json={"address": "부산"}).json()["data"]["representative"] == "홍길동"  # 안 보낸 칸 유지
    got = client.get(URL).json()["data"]
    assert got["address"] == "부산" and got["name"] == "회사A"


def test_staff_reads_but_cannot_update(client, world):
    """담당자는 조회 200, 수정 403(값은 안 바뀐다)."""
    login_as(client, "admin@a.test")
    client.patch(URL, json=FULL)
    login_as(client, "staff@a.test")
    assert client.get(URL).json()["data"]["representative"] == "홍길동"
    assert client.patch(URL, json={"representative": "해킹"}).status_code == 403
    assert client.get(URL).json()["data"]["representative"] == "홍길동"


def test_other_company_not_exposed(client, world):
    """회사 B 관리자가 저장한 값은 회사 A 에게 안 보이고, 본문의 id·company_id 는 무시된다."""
    login_as(client, "admin@b.test")
    client.patch(URL, json={"representative": "비밀", "company_id": world["a_company"].id, "id": world["a_company"].id})
    login_as(client, "admin@a.test")
    assert client.get(URL).json()["data"]["representative"] is None
    login_as(client, "admin@b.test")
    assert client.get(URL).json()["data"]["representative"] == "비밀"


def test_empty_values_ok(client, world):
    """아무것도 안 채운 조회·빈 값 저장·비우기 모두 정상."""
    login_as(client, "admin@a.test")
    assert client.get(URL).json()["data"]["business_number"] is None
    assert client.patch(URL, json={}).status_code == 200
    client.patch(URL, json=FULL)
    cleared = client.patch(URL, json={"business_number": "", "representative": None, "address": ""}).json()["data"]
    assert cleared["business_number"] is None and cleared["representative"] is None and cleared["address"] is None
    assert cleared["phone"] == "02-123-4567"


@pytest.mark.parametrize("value", ["12345", "123456789a", "123-456-7890", "12-345-67890", "12345678901", 1234567890], ids=str)
def test_business_number_format_422(client, world, value):
    """10자리 숫자가 아니거나 하이픈 자리가 틀리면 422."""
    login_as(client, "admin@a.test")
    r = client.patch(URL, json={"business_number": value})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_requires_login(client, world):
    assert client.get(URL).status_code == 401


def test_supplier_payment_terms(client, world):
    """공급업체 지불조건: 등록·수정·비우기."""
    login_as(client)
    sid = client.post("/api/v1/suppliers", json={"name": "다라", "lead_time_days": 2, "payment_terms": "월말 마감"}).json()["data"]["id"]
    assert client.get(f"/api/v1/suppliers/{sid}").json()["data"]["payment_terms"] == "월말 마감"
    assert client.patch(f"/api/v1/suppliers/{sid}", json={"payment_terms": None}).json()["data"]["payment_terms"] is None
