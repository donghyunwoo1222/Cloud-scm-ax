import os  # 환경 변수 읽기
from pathlib import Path  # 파일 경로 다루기

import pytest  # 테스트 도구
from alembic import command  # 코드에서 alembic upgrade/downgrade 를 부르는 도구
from alembic.config import Config  # alembic.ini 읽기
from fastapi.testclient import TestClient  # 서버를 띄우지 않고 앱에 요청을 보내는 도구
from sqlalchemy import create_engine, make_url, text  # DB 연결, 주소 해석, SQL 문장
from sqlalchemy.orm import Session  # ORM 세션

from app.auth.security import hash_password  # 테스트 사용자 비밀번호 해시
from app.db import get_db  # 앱이 쓰는 DB 세션 의존성
from app.main import app  # 테스트할 앱
from app.models import Company, Supplier, User  # 준비 데이터 표
from tests.helpers import PASSWORD  # 테스트 사용자 공통 비밀번호

# 테스트 전용 DB. 개발용 DB(scm)와 이름을 나눠, 테스트가 개발 데이터를 지우지 않게 한다
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",  # CI 등에서 바꾸고 싶으면 이 환경 변수를 준다
    "postgresql+psycopg://scm:scm_local_pw@localhost:5433/scm_test",  # 기본값: 로컬 Docker DB 안의 scm_test
)
BACKEND_DIR = Path(__file__).resolve().parents[1]  # backend/ 폴더 (alembic.ini 위치)


def create_test_database_if_missing(url: str) -> None:
    """scm_test DB가 없으면 만든다 (로컬 Docker DB에는 처음에 scm만 있다)."""
    target = make_url(url)  # 주소를 부분별로 나눈다
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")  # 기본 DB로 접속 (CREATE DATABASE는 트랜잭션 밖에서만 된다)
    with admin.connect() as conn:  # 접속해서
        exists = conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database})  # 같은 이름 DB가 있는지 본다
        if not exists:  # 없으면
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))  # 새로 만든다
    admin.dispose()  # 접속을 정리한다


@pytest.fixture(scope="session")
def engine():
    """테스트 한 번 실행에 한 번: 표를 지우고 마이그레이션으로 처음부터 다시 만든다."""
    create_test_database_if_missing(TEST_DATABASE_URL)  # 테스트 DB 준비
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))  # alembic 설정 읽기
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))  # 어느 폴더에서 실행해도 마이그레이션 파일을 찾게
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))  # 개발 DB가 아닌 테스트 DB에 적용
    command.downgrade(cfg, "base")  # 이전 실행에서 남은 표를 모두 지운다 (downgrade 도 함께 검증)
    command.upgrade(cfg, "head")  # 실제 마이그레이션 파일로 표 7개를 만든다 (모델이 아니라 마이그레이션을 검증)
    eng = create_engine(TEST_DATABASE_URL)  # 테스트가 쓸 연결 묶음
    yield eng  # 테스트들에게 넘긴다
    eng.dispose()  # 끝나면 정리


@pytest.fixture
def session(engine):
    """테스트 하나마다: 트랜잭션 안에서 실행하고 끝나면 되돌려, 테스트끼리 데이터가 섞이지 않게 한다.

    준비 데이터를 넣는 fixture 는 끝에 session.commit() 을 부른다. 그래야 앱이 오류(409 등) 뒤 rollback 해도
    준비 데이터는 남는다. 이 commit 은 세이브포인트만 확정하므로 테스트가 끝나면 함께 되돌려진다.
    """
    conn = engine.connect()  # 연결 하나
    trans = conn.begin()  # 바깥 트랜잭션 시작
    sess = Session(bind=conn, join_transaction_mode="create_savepoint")  # 이 연결을 쓰는 세션. 코드가 commit 해도 세이브포인트만 확정돼 바깥 트랜잭션은 그대로
    yield sess  # 테스트에 넘긴다
    sess.close()  # 세션 닫기
    trans.rollback()  # 테스트가 넣은 행을 모두 되돌린다
    conn.close()  # 연결 반납


@pytest.fixture
def client(session):
    """앱이 개발 DB 대신 이 테스트의 세션(scm_test, 끝나면 되돌림)을 쓰게 바꾼 클라이언트."""
    app.dependency_overrides[get_db] = lambda: session  # get_db 를 테스트 세션으로 바꿔 끼운다
    with TestClient(app) as c:  # 쿠키를 기억하는 가짜 브라우저
        yield c
    app.dependency_overrides.clear()  # 다음 테스트에 영향 없게 원래대로


@pytest.fixture
def world(session):
    """공통 준비 데이터: 회사 A·B, 각 회사에 관리자·담당자·공급업체 1개.

    키: a_company, a_admin(admin@a.test), a_staff(staff@a.test), a_supplier('A업체', 리드타임 5), b_ 도 같은 모양.
    """
    out = {}
    for key in ("a", "b"):  # 회사 A, B
        company = Company(name=f"회사{key.upper()}")  # 회사A, 회사B
        session.add(company)
        session.flush()  # company.id 생성
        out[f"{key}_company"] = company
        for role in ("ADMIN", "STAFF"):  # 관리자, 담당자
            user = User(
                company_id=company.id, name=f"{key}-{role}", email=f"{role.lower()}@{key}.test",  # 예) admin@a.test
                password_hash=hash_password(PASSWORD), role=role,
            )
            session.add(user)
            out[f"{key}_{role.lower()}"] = user  # 예) out["a_admin"]
        supplier = Supplier(company_id=company.id, name=f"{key.upper()}업체", lead_time_days=5)  # A업체, B업체
        session.add(supplier)
        out[f"{key}_supplier"] = supplier
    session.commit()  # 준비 데이터 확정 (앱이 오류 뒤 rollback 해도 남는다, 테스트 끝에는 함께 되돌림)
    return out
