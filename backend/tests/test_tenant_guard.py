"""회사 분리·역할 검사 공통 장치 테스트.

업무 API(공급업체 등)는 아직 없으므로, 이 파일 안에서만 쓰는 임시 앱·경로로 공통 함수를 검증한다.
실제 앱(app.main)에는 테스트용 경로를 넣지 않는다.
"""

import pytest  # 테스트 도구
from fastapi import APIRouter, FastAPI  # 임시 경로·앱
from fastapi.testclient import TestClient  # 가짜 브라우저
from pydantic import BaseModel  # 임시 요청 모양

from app.api import auth as auth_api  # 진짜 로그인 경로 (쿠키 발급)
from app.auth.deps import AdminUser, CurrentUser  # 검사할 의존성
from app.auth.security import hash_password  # 테스트 사용자 비밀번호
from app.db import DB, get_db  # DB 세션
from app.errors import register_error_handlers  # 공통 오류 모양
from app.models import Company, Supplier, User  # 표
from app.services.tenant import check_ref, get_owned, scoped  # 검사할 공통 함수

PASSWORD = "test-password"  # 모든 테스트 사용자 공통 비밀번호

# ----- 테스트 전용 임시 경로: 이후 진짜 API가 공통 함수를 쓰는 모양 그대로 -----
router = APIRouter()  # 임시 경로 묶음


class ProductDraft(BaseModel):
    default_supplier_id: int  # 본문이 가리키는 공급업체 id


@router.get("/suppliers")  # 목록
def list_suppliers(user: CurrentUser, db: DB) -> dict:
    rows = db.scalars(scoped(user.company_id, Supplier).order_by(Supplier.id)).all()  # 회사 조건이 붙은 시작점
    return {"data": [{"id": s.id, "name": s.name} for s in rows]}


@router.get("/suppliers/{supplier_id}")  # 상세
def get_supplier(supplier_id: int, user: CurrentUser, db: DB) -> dict:
    s = get_owned(user.company_id, db, Supplier, supplier_id)  # 같은 회사 행만, 아니면 404
    return {"data": {"id": s.id, "name": s.name}}


@router.post("/products")  # 본문 참조 검사
def create_product(data: ProductDraft, user: CurrentUser, db: DB) -> dict:
    check_ref(user.company_id, db, Supplier, data.default_supplier_id, "default_supplier_id")  # 다른 회사 업체면 404
    return {"data": "ok"}


@router.post("/admin-only")  # 관리자 전용
def admin_only(user: AdminUser) -> dict:
    return {"data": "ok"}


guard_app = FastAPI()  # 테스트 전용 앱
register_error_handlers(guard_app)  # 진짜 앱과 같은 오류 모양
guard_app.include_router(auth_api.router, prefix="/api/v1")  # 진짜 로그인 경로
guard_app.include_router(router, prefix="/api/v1")  # 임시 경로


# ----- 준비 데이터: 회사 A·B, 각 관리자·담당자·공급업체 1개 -----
@pytest.fixture
def world(session):
    """회사 2곳과 각 회사의 관리자·담당자·공급업체."""
    out = {}
    for key in ("a", "b"):  # 회사 A, B
        company = Company(name=f"회사{key.upper()}")
        session.add(company)
        session.flush()  # company.id 생성
        for role in ("ADMIN", "STAFF"):  # 관리자, 담당자
            session.add(User(
                company_id=company.id, name=f"{key}-{role}", email=f"{role.lower()}@{key}.test",
                password_hash=hash_password(PASSWORD), role=role,
            ))
        supplier = Supplier(company_id=company.id, name=f"{key.upper()}업체", lead_time_days=3)
        session.add(supplier)
        session.flush()  # supplier.id 생성
        out[key] = {"company": company, "supplier": supplier}
    return out


@pytest.fixture
def client(session):
    """임시 앱이 테스트 세션(scm_test, 끝나면 되돌림)을 쓰게 한 클라이언트."""
    guard_app.dependency_overrides[get_db] = lambda: session
    with TestClient(guard_app) as c:
        yield c
    guard_app.dependency_overrides.clear()


def login_as(client, email: str) -> None:
    assert client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200  # 쿠키를 받는다


# ----- 테스트 -----
def test_own_company_detail(client, world):
    """A 사용자가 A 공급업체 상세 → 200."""
    login_as(client, "staff@a.test")
    response = client.get(f"/api/v1/suppliers/{world['a']['supplier'].id}")
    assert response.status_code == 200
    assert response.json()["data"]["name"] == "A업체"


def test_other_company_and_missing_id_look_the_same(client, world):
    """A 사용자가 B 공급업체 상세 → 404, 없는 id → 404. 두 응답이 완전히 같다."""
    login_as(client, "staff@a.test")
    other = client.get(f"/api/v1/suppliers/{world['b']['supplier'].id}")  # 있지만 B 회사 것
    missing = client.get("/api/v1/suppliers/999999")  # 아예 없는 id
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()  # code·message·details 모두 같다 → B 업체가 있는지 알 수 없다
    assert other.json()["error"]["code"] == "NOT_FOUND"


def test_body_reference_to_other_company(client, world):
    """A 사용자가 본문에 B 공급업체 id → 404, details 에 칸 이름. A 업체 id 는 통과."""
    login_as(client, "staff@a.test")
    bad = client.post("/api/v1/products", json={"default_supplier_id": world["b"]["supplier"].id})
    assert bad.status_code == 404
    assert bad.json()["error"]["details"] == [{"field": "default_supplier_id", "reason": "not_found"}]
    good = client.post("/api/v1/products", json={"default_supplier_id": world["a"]["supplier"].id})
    assert good.status_code == 200


def test_list_has_only_own_company(client, world):
    """A 목록에는 A 업체만 있고 B 업체는 섞이지 않는다."""
    login_as(client, "admin@a.test")
    names = [s["name"] for s in client.get("/api/v1/suppliers").json()["data"]]
    assert names == ["A업체"]


def test_admin_only_route(client, world):
    """담당자 → 403 FORBIDDEN_ROLE, 관리자 → 200."""
    login_as(client, "staff@a.test")
    staff = client.post("/api/v1/admin-only")
    assert staff.status_code == 403
    assert staff.json()["error"]["code"] == "FORBIDDEN_ROLE"
    login_as(client, "admin@a.test")  # 관리자로 다시 로그인 (쿠키가 바뀐다)
    assert client.post("/api/v1/admin-only").status_code == 200


@pytest.mark.parametrize(
    "method, path",
    [("get", "/api/v1/suppliers"), ("get", "/api/v1/suppliers/1"), ("post", "/api/v1/admin-only")],
)
def test_not_logged_in(client, world, method, path):
    """로그인 안 함 → 401 (역할 검사보다 로그인 확인이 먼저)."""
    response = getattr(client, method)(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
