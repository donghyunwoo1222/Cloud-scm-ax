"""동시 요청 테스트: 행 잠금으로 '한 줄 세우기'가 되는지 실제 DB 연결 여러 개로 확인한다.

규칙을 지키는 코드가 잠금 없이도 한 번씩은 통과할 수 있으므로, 여러 건을 같은 순간에 보내 겹치게 만든다.
"""

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 업무 오류
from app.models import Company, Product, Supplier, User  # 표
from app.schemas.users import UserUpdate  # 직원 수정 요청 모양
from app.services import stock as stock_service  # 재고 (register_movement)
from app.services import users as users_service  # 직원 계정 (LAST_ADMIN)
from tests.concurrency import delete_companies, run_at_once, run_in_new_session  # 동시 요청 도구


@pytest.fixture
def committed_company(engine):
    """진짜로 commit 한 회사 하나(관리자 1명, 공급업체 1개, 품목 1개). 테스트가 끝나면 지운다."""
    def create(session):
        company = Company(name="동시성상사")
        session.add(company)
        session.flush()  # company.id 생성
        admin = User(company_id=company.id, name="관리자0", email=f"admin0-{company.id}@concurrency.test",
                     password_hash="x", role="ADMIN")  # 로그인은 하지 않으므로 해시는 아무 값
        supplier = Supplier(company_id=company.id, name="동시성업체", lead_time_days=3)
        session.add_all([admin, supplier])
        session.flush()  # id 생성
        product = Product(company_id=company.id, sku="CC-1", name="동시성품목", unit="개", unit_cost=1000,
                          default_supplier_id=supplier.id)
        session.add(product)
        session.commit()  # 진짜 확정 (다른 연결에서도 보인다)
        return {"company_id": company.id, "admin_id": admin.id, "product_id": product.id}

    data = run_in_new_session(engine, create)
    yield data
    delete_companies(engine, [data["company_id"]])  # 테스트 데이터 정리


def sell(engine, data, quantity):
    """새 세션(= 요청 하나)으로 판매 출고를 등록한다."""
    return run_in_new_session(engine, lambda s: stock_service.register_movement(
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="SALE",
        direction="OUT", quantity=quantity, movement_date=seoul_today(), sales_channel="OWN_MALL",
    ))


@pytest.mark.parametrize("requests", [2, 8], ids=["two", "eight"])
def test_concurrent_sales_only_one_succeeds(engine, committed_company, requests):
    """#29 완료 기준: 재고 52개에 30개씩 동시에 보내면 한 건만 성공하고 재고는 22 (음수가 되지 않는다)."""
    data = committed_company
    run_in_new_session(engine, lambda s: stock_service.register_movement(  # 먼저 52개 입고
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="RECEIPT",
        direction="IN", quantity=52, movement_date=seoul_today(),
    ))

    results = run_at_once(*[lambda: sell(engine, data, 30) for _ in range(requests)])  # 30개 출고를 동시에

    successes = [r for r in results if not isinstance(r, Exception)]  # 성공한 요청
    failures = [r for r in results if isinstance(r, Exception)]  # 실패한 요청
    assert len(successes) == 1  # 52 − 30 = 22, 두 번째 30은 들어갈 수 없다
    assert all(isinstance(e, AppError) and e.code == "INSUFFICIENT_STOCK" for e in failures)  # 실패는 모두 재고 부족
    assert successes[0][1] == 22  # 성공한 요청이 본 등록 직후 재고
    final = run_in_new_session(engine, lambda s: stock_service.current_stock(data["company_id"], s, data["product_id"]))
    assert final == 22  # 실제 이력 합계도 22


def test_concurrent_admin_demotions_keep_one_admin(engine, committed_company):
    """#24 LAST_ADMIN: 관리자 5명이 같은 순간 모두 스스로 담당자가 되려 해도 활성 관리자는 1명 남는다."""
    data = committed_company

    def add_admins(session):
        for i in range(1, 5):  # 관리자 4명 더 (총 5명)
            session.add(User(company_id=data["company_id"], name=f"관리자{i}", role="ADMIN", password_hash="x",
                             email=f"admin{i}-{data['company_id']}@concurrency.test"))
        session.commit()
        return list(session.scalars(select(User.id).where(User.company_id == data["company_id"])))

    admin_ids = run_in_new_session(engine, add_admins)  # 5명의 id

    def demote(user_id):
        return run_in_new_session(engine, lambda s: users_service.update_user(
            data["company_id"], s, user_id, UserUpdate(role="STAFF")))

    results = run_at_once(*[lambda uid=uid: demote(uid) for uid in admin_ids])  # 5명이 동시에 내려가기

    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1  # 마지막 한 명만 막힌다
    assert isinstance(failures[0], AppError) and failures[0].code == "LAST_ADMIN"
    left = run_in_new_session(engine, lambda s: s.scalar(
        select(func.count()).select_from(User).where(User.company_id == data["company_id"], User.role == "ADMIN")))
    assert left == 1  # 관리자가 0명이 되지 않았다
