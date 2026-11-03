"""공급업체 API (#25) 테스트."""

import pytest  # 테스트 도구

from tests.helpers import login_as  # 공통 로그인 (준비 데이터 world 는 conftest)

URL = "/api/v1/suppliers"  # 공급업체 경로


def new_supplier(**override) -> dict:
    """공급업체 등록 요청 본문."""
    return {"name": "다라유통", "lead_time_days": 3, **override}


# ----- 완료 기준 1: 등록·수정·비활성이 된다 (관리자·담당자 모두) -----
@pytest.mark.parametrize("email", ["staff@a.test", "admin@a.test"], ids=["staff", "admin"])
def test_create_update_deactivate(client, world, email):
    """등록 201 → 수정 → 비활성 → 다시 활성. 담당자도 관리자도 된다."""
    login_as(client, email)
    created = client.post(URL, json=new_supplier(name="  다라유통  ", phone="010-1234-5678"))
    assert created.status_code == 201
    data = created.json()["data"]
    assert data["name"] == "다라유통"  # 앞뒤 공백 제거
    assert data["is_active"] is True
    sid = data["id"]

    updated = client.patch(f"{URL}/{sid}", json={"lead_time_days": 7, "phone": None})  # 리드타임 변경, 연락처 비우기
    assert updated.json()["data"]["lead_time_days"] == 7
    assert updated.json()["data"]["phone"] is None
    assert updated.json()["data"]["name"] == "다라유통"  # 보내지 않은 칸은 그대로

    assert client.patch(f"{URL}/{sid}", json={"is_active": False}).json()["data"]["is_active"] is False  # 비활성
    assert client.get(f"{URL}/{sid}").json()["data"]["is_active"] is False  # 상세는 비활성도 보인다
    assert client.patch(f"{URL}/{sid}", json={"is_active": True}).json()["data"]["is_active"] is True  # 다시 활성


def test_no_delete_route(client, world):
    """삭제 경로는 없다 (405 Method Not Allowed)."""
    login_as(client)
    assert client.delete(f"{URL}/{world['a_supplier'].id}").status_code == 405


# ----- 완료 기준 2: 리드타임은 0 이상 정수만 -----
@pytest.mark.parametrize("value", [-1, 3.5, 3.0, "3", None, True], ids=["negative", "decimal", "float", "string", "null", "bool"])
def test_lead_time_rejects_non_integer(client, world, value):
    """음수·소수·문자·null·참거짓은 422 VALIDATION_ERROR, 어느 칸인지 details 에."""
    login_as(client)
    response = client.post(URL, json=new_supplier(lead_time_days=value))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert response.json()["error"]["details"][0]["field"] == "lead_time_days"


def test_lead_time_zero_ok_and_patch_checked(client, world):
    """리드타임 0 은 허용, 수정에서도 음수는 422, null 로 비우기도 422."""
    login_as(client)
    assert client.post(URL, json=new_supplier(lead_time_days=0)).status_code == 201
    sid = world["a_supplier"].id
    assert client.patch(f"{URL}/{sid}", json={"lead_time_days": -3}).status_code == 422
    assert client.patch(f"{URL}/{sid}", json={"lead_time_days": None}).status_code == 422  # 필수 칸 비우기


# ----- 같은 이름 -----
def test_duplicate_name(client, world):
    """같은 회사 같은 이름(공백만 다름) 409 DUPLICATE_NAME, 이름 바꾸기도 409. 다른 회사의 같은 이름은 허용."""
    login_as(client)
    dup = client.post(URL, json=new_supplier(name=" A업체 "))  # 이미 있는 'A업체'
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "DUPLICATE_NAME"
    other = client.post(URL, json=new_supplier(name="새업체")).json()["data"]
    assert client.patch(f"{URL}/{other['id']}", json={"name": "A업체"}).json()["error"]["code"] == "DUPLICATE_NAME"
    assert client.post(URL, json=new_supplier(name="B업체")).status_code == 201  # 회사 B 에 있는 이름이지만 A 에선 허용


# ----- 회사 분리 (API 마다) -----
def test_detail_other_company_is_404(client, world):
    """GET 상세: B 업체 id → 404, 없는 id 와 같은 응답."""
    login_as(client)
    other = client.get(f"{URL}/{world['b_supplier'].id}")
    missing = client.get(f"{URL}/999999")
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


def test_patch_other_company_is_404(client, world, session):
    """PATCH: B 업체 id → 404, B 업체는 그대로."""
    login_as(client)
    response = client.patch(f"{URL}/{world['b_supplier'].id}", json={"is_active": False})
    assert response.status_code == 404
    session.refresh(world["b_supplier"])  # DB 에서 다시 읽기
    assert world["b_supplier"].is_active is True


def test_list_and_create_stay_in_own_company(client, world):
    """GET 목록: B 업체가 없다. POST: 본문의 company_id 는 무시되고 A 회사에 만들어진다."""
    login_as(client)
    client.post(URL, json=new_supplier(company_id=world["b_supplier"].company_id))  # 몰래 넣은 회사
    names = [s["name"] for s in client.get(URL).json()["data"]]
    assert set(names) == {"A업체", "다라유통"}  # 새 업체가 A 목록에 있고 B업체는 없다
    login_as(client, "staff@b.test")
    assert [s["name"] for s in client.get(URL).json()["data"]] == ["B업체"]  # B 목록에 섞이지 않았다


# ----- 목록: 최신순·쪽 나누기·비활성 필터·검색 -----
def test_list_paging_filter_search(client, world):
    """최신순, meta, 비활성 기본 숨김, q 부분 일치(대소문자 무시, % 는 글자 그대로)."""
    login_as(client)
    for name in ("Alpha 상사", "beta유통", "50% 할인몰"):  # 업체 3개 더 (총 4개)
        client.post(URL, json=new_supplier(name=name))
    client.patch(f"{URL}/{world['a_supplier'].id}", json={"is_active": False})  # 'A업체' 비활성 → 활성 3개

    body = client.get(URL).json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 3}  # 비활성 제외
    assert body["data"][0]["name"] == "50% 할인몰"  # 가장 최근 등록이 먼저
    assert client.get(URL, params={"include_inactive": "true"}).json()["meta"]["total"] == 4  # 비활성 포함
    assert len(client.get(URL, params={"page": 2, "page_size": 2}).json()["data"]) == 1  # 2개씩 2쪽 → 1개

    def search(q):
        return [s["name"] for s in client.get(URL, params={"q": q}).json()["data"]]

    assert search("ALPHA") == ["Alpha 상사"]  # 대소문자 무시
    assert search("유통") == ["beta유통"]  # 부분 일치
    assert search("%") == ["50% 할인몰"]  # % 가 "아무 글자"로 해석되지 않는다
    assert search("A업체") == []  # 비활성은 검색에서도 기본 숨김


# ----- 로그인 -----
def test_anonymous_is_401(client, world):
    """로그인 안 함 → 401."""
    assert client.get(URL).status_code == 401
    assert client.post(URL, json=new_supplier()).status_code == 401
