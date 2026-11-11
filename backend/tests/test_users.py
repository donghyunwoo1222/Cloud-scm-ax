"""직원 계정 관리 API (#24) 테스트."""

import pytest  # 테스트 도구

from app.models import User  # 사용자 표
from tests.helpers import PASSWORD, login_as  # 공통 비밀번호·로그인 (준비 데이터 world 는 conftest)

URL = "/api/v1/users"  # 직원 계정 경로


def new_user(**override) -> dict:
    """직원 생성 요청 본문 (기본: 담당자)."""
    return {"name": "새직원", "email": "new@a.test", "password": PASSWORD, "role": "STAFF", **override}


# ----- 완료 기준 1: 생성·역할 변경·비활성이 된다 -----
def test_create_user(client, world):
    """관리자가 직원 생성 → 201, 이메일은 소문자, 해시는 응답에 없음, 새 직원이 로그인된다."""
    login_as(client, "admin@a.test")
    response = client.post(URL, json=new_user(email="  New@A.TEST "))
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["email"] == "new@a.test"  # 공백 제거·소문자
    assert data["role"] == "STAFF" and data["is_active"] is True
    assert "password" not in response.text  # 해시 칸 없음
    login_as(client, "new@a.test")  # 임시 비밀번호로 로그인된다


def test_change_role_and_deactivate(client, world):
    """역할 변경(담당자→관리자), 비활성, 다시 활성이 된다. 비활성 직원은 로그인 불가."""
    login_as(client, "admin@a.test")
    staff_id = world["a_staff"].id
    assert client.patch(f"{URL}/{staff_id}", json={"role": "ADMIN"}).json()["data"]["role"] == "ADMIN"
    assert client.patch(f"{URL}/{staff_id}", json={"is_active": False}).json()["data"]["is_active"] is False
    login_fail = client.post("/api/v1/auth/login", json={"email": "staff@a.test", "password": PASSWORD})
    assert login_fail.status_code == 401  # 비활성은 로그인 불가 (#22)
    login_as(client, "admin@a.test")
    assert client.patch(f"{URL}/{staff_id}", json={"is_active": True}).json()["data"]["is_active"] is True  # 다시 활성


# ----- 완료 기준 2: 마지막 관리자의 역할 변경·비활성이 막힌다 -----
@pytest.mark.parametrize("change", [{"role": "STAFF"}, {"is_active": False}], ids=["demote", "deactivate"])
def test_last_admin_protected(client, world, change):
    """활성 관리자가 한 명뿐이면 그 사람의 역할 변경·비활성은 409 LAST_ADMIN (자기 자신 포함)."""
    login_as(client, "admin@a.test")
    response = client.patch(f"{URL}/{world['a_admin'].id}", json=change)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "LAST_ADMIN"
    assert client.get("/api/v1/me").json()["data"]["role"] == "ADMIN"  # 바뀌지 않았다


def test_admin_can_step_down_when_another_admin_exists(client, world):
    """다른 활성 관리자가 있으면 자기 자신을 담당자로 내릴 수 있다. 그 뒤 남은 관리자는 다시 보호된다."""
    login_as(client, "admin@a.test")
    client.patch(f"{URL}/{world['a_staff'].id}", json={"role": "ADMIN"})  # 관리자 2명이 된다
    assert client.patch(f"{URL}/{world['a_admin'].id}", json={"role": "STAFF"}).status_code == 200  # 자기 자신을 내림
    login_as(client, "staff@a.test")  # 이제 이 사람이 유일한 관리자
    assert client.patch(f"{URL}/{world['a_staff'].id}", json={"is_active": False}).json()["error"]["code"] == "LAST_ADMIN"


def test_inactive_admin_does_not_count(client, world, session):
    """비활성 관리자는 '활성 관리자 1명'에 세지 않는다."""
    session.add(User(company_id=world["a_admin"].company_id, name="퇴사관리자", email="old@a.test",
                     password_hash="x", role="ADMIN", is_active=False))  # 비활성 관리자
    session.flush()
    login_as(client, "admin@a.test")
    assert client.patch(f"{URL}/{world['a_admin'].id}", json={"role": "STAFF"}).json()["error"]["code"] == "LAST_ADMIN"


# ----- 완료 기준 3: 이미 쓰는 이메일이면 EMAIL_TAKEN -----
def test_duplicate_email(client, world):
    """다른 회사 직원 이메일이어도(전체 유일) 409 EMAIL_TAKEN. 대소문자만 달라도 같은 이메일."""
    login_as(client, "admin@a.test")
    response = client.post(URL, json=new_user(email="STAFF@B.test"))  # 회사 B 담당자의 이메일
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_short_password(client, world):
    """임시 비밀번호 7자 → 422 (#22 의 validate_password 재사용)."""
    login_as(client, "admin@a.test")
    response = client.post(URL, json=new_user(password="1234567"))
    assert response.status_code == 422
    assert response.json()["error"]["message"] == "비밀번호는 8자 이상이어야 합니다."


# ----- 회사 분리 (API 마다) -----
def test_patch_other_company_user_is_404(client, world):
    """PATCH: B 회사 직원 id → 404, 없는 id 와 같은 응답. B 직원은 그대로."""
    login_as(client, "admin@a.test")
    other = client.patch(f"{URL}/{world['b_staff'].id}", json={"is_active": False})
    missing = client.patch(f"{URL}/999999", json={"is_active": False})
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()
    login_as(client, "staff@b.test")  # B 직원은 여전히 로그인된다 (비활성이 안 됐다)


def test_create_ignores_company_in_body(client, world):
    """POST: 본문에 B 회사 id 를 넣어도 무시되고 A 회사 직원으로 만들어진다 (회사는 토큰에서만)."""
    login_as(client, "admin@a.test")
    client.post(URL, json=new_user(company_id=world["b_admin"].company_id))  # 몰래 넣은 company_id
    login_as(client, "new@a.test")
    assert client.get("/api/v1/me").json()["data"]["company"]["name"] == "회사A"


def test_list_only_own_company(client, world):
    """GET: A 목록에 B 직원이 없다."""
    login_as(client, "admin@a.test")
    emails = {u["email"] for u in client.get(URL).json()["data"]}
    assert emails == {"admin@a.test", "staff@a.test"}


# ----- 목록: 최신순·쪽 나누기·비활성 필터 -----
def test_list_paging_order_and_inactive_filter(client, world):
    """기본 20개·최신순, page_size 로 자르기, 비활성은 기본 숨김·include_inactive=true 로 포함."""
    login_as(client, "admin@a.test")
    for i in range(3):  # 직원 3명 더 (총 5명)
        client.post(URL, json=new_user(email=f"n{i}@a.test"))
    client.patch(f"{URL}/{world['a_staff'].id}", json={"is_active": False})  # 1명 비활성 → 활성 4명

    body = client.get(URL).json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 4}  # 기본 20개, 비활성 제외
    assert body["data"][0]["email"] == "n2@a.test"  # 가장 최근에 만든 직원이 먼저

    page2 = client.get(URL, params={"page": 2, "page_size": 3}).json()  # 3개씩 2쪽 → 4번째 1명
    assert len(page2["data"]) == 1 and page2["meta"]["total"] == 4

    all_rows = client.get(URL, params={"include_inactive": "true"}).json()
    assert all_rows["meta"]["total"] == 5  # 비활성 포함
    assert client.get(URL, params={"page": 0}).json()["error"]["code"] == "VALIDATION_ERROR"  # 0쪽은 422


# ----- 권한 -----
@pytest.mark.parametrize(
    "method, path, body",
    [("get", URL, None), ("post", URL, new_user()), ("patch", f"{URL}/1", {"role": "ADMIN"})],
    ids=["list", "create", "update"],
)
def test_staff_forbidden_and_anonymous_unauthenticated(client, world, method, path, body):
    """담당자 → 403 FORBIDDEN_ROLE, 로그인 안 함 → 401."""
    kwargs = {"json": body} if body else {}
    assert getattr(client, method)(path, **kwargs).status_code == 401  # 로그인 전
    login_as(client, "staff@a.test")
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN_ROLE"


# ---- #169 임시 비밀번호 최초 변경 ----

def make_temp_staff(client, world):
    """관리자가 직원을 만들고, 그 직원이 임시 비밀번호로 로그인한 상태(새 클라이언트가 아니라 같은 클라이언트를 갈아탄다)."""
    login_as(client, "admin@a.test")  # 관리자 로그인
    created = client.post(URL, json={"name": "신입", "email": "new@a.test", "password": "temp-pass-1", "role": "STAFF"})
    assert created.status_code == 201
    client.post("/api/v1/auth/logout")  # 관리자 쿠키 삭제
    return client.post("/api/v1/auth/login", json={"email": "new@a.test", "password": "temp-pass-1"})  # 임시 비밀번호 로그인


def test_temp_password_blocks_other_apis_until_changed(client, world):
    """임시 비밀번호로 로그인하면 /me 만 되고 다른 API 는 403, 변경하면 풀린다."""
    assert make_temp_staff(client, world).status_code == 200  # 로그인 자체는 된다
    assert client.get("/api/v1/me").json()["data"]["must_change_password"] is True  # 화면이 보는 표시
    blocked = client.get("/api/v1/products")  # 다른 기능
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"
    changed = client.post("/api/v1/auth/password", json={"current_password": "temp-pass-1", "new_password": "my-new-pass-2"})
    assert changed.status_code == 200
    assert changed.json()["data"]["must_change_password"] is False  # 표시 해제
    assert client.get("/api/v1/products").status_code == 200  # 이제 쓸 수 있다
    client.post("/api/v1/auth/logout")
    assert client.post("/api/v1/auth/login", json={"email": "new@a.test", "password": "temp-pass-1"}).status_code == 401  # 옛 비밀번호는 끝
    assert client.post("/api/v1/auth/login", json={"email": "new@a.test", "password": "my-new-pass-2"}).status_code == 200


def test_change_password_rules(client, world):
    """현재 비밀번호 틀림 401, 8자 미만 422, 현재와 같음 422 이고 표시는 그대로 켜져 있다."""
    make_temp_staff(client, world)
    url = "/api/v1/auth/password"
    wrong = client.post(url, json={"current_password": "nope-nope", "new_password": "my-new-pass-2"})
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (401, "WRONG_CURRENT_PASSWORD")
    assert client.post(url, json={"current_password": "temp-pass-1", "new_password": "short"}).status_code == 422
    assert client.post(url, json={"current_password": "temp-pass-1", "new_password": "temp-pass-1"}).status_code == 422
    assert client.get("/api/v1/me").json()["data"]["must_change_password"] is True  # 실패했으니 그대로


def test_signup_admin_and_seeded_users_not_forced(client, world):
    """회사 가입 관리자와 기존(world) 계정은 변경을 강제하지 않는다."""
    login_as(client, "staff@a.test")
    assert client.get("/api/v1/me").json()["data"]["must_change_password"] is False
