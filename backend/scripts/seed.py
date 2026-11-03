"""개발용 시드 데이터 넣기·지우기. 개발 DB(.env 의 DATABASE_URL, 보통 scm)에만 쓴다.

사용법 (backend/ 폴더에서):
    .venv\\Scripts\\python -m scripts.seed          # 시드를 지우고 새로 넣는다 (여러 번 실행해도 같은 결과)
    .venv\\Scripts\\python -m scripts.seed --clear  # 시드만 지운다

시드 회사는 사용자 이메일이 @seed.local 로 끝나는 회사로 알아본다. 그 회사의 데이터(화면에서 추가한 것 포함)만 지운다.
"""

import argparse  # 명령줄 옵션(--clear) 읽기

from sqlalchemy import create_engine, delete, make_url, select  # DB 연결, 삭제·조회 문
from sqlalchemy.orm import Session  # DB 세션

from app.auth.security import hash_password  # 비밀번호 해시
from app.config import settings  # .env 의 DATABASE_URL
from app.models import (  # 표 7개
    Company,
    InventoryMovement,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)

SEED_DOMAIN = "@seed.local"  # 시드 계정 이메일 끝. 이걸로 시드 회사를 찾는다
SEED_PASSWORD = "seed-pass-1234"  # 개발용 시드 계정 비밀번호 (개발 DB 전용, 실제 서비스에 쓰지 말 것)

# 회사 2곳: (회사명, 이메일 앞부분, 공급업체 2개(이름, 리드타임), 품목 5개(SKU, 이름, 단위, 단가, 안전재고, 공급업체 번호))
COMPANIES = [
    ("가나패션(시드)", "gana", [("다라섬유", 5), ("마바물류", 3)], [
        ("TS-BK-M", "기본 티셔츠 검정 M", "개", 5000, 20, 0),
        ("TS-WH-L", "기본 티셔츠 흰색 L", "개", 5000, 20, 0),
        ("CAP-01", "볼캡", "개", 7000, 10, 0),
        ("SOCK-3P", "양말 3켤레", "묶음", 3000, 30, 1),
        ("BAG-EC", "에코백", "개", 4000, 5, 1),
    ]),
    ("사아마트(시드)", "saa", [("자차식품", 2), ("카타음료", 4)], [
        ("WTR-500", "생수 500ml 20입", "박스", 6000, 15, 1),
        ("RMN-5P", "라면 5입", "묶음", 3500, 25, 0),
        ("CF-STK", "커피믹스 100입", "박스", 12000, 8, 0),
        ("TIS-30", "화장지 30롤", "팩", 15000, 6, 0),
        ("JCE-1L", "오렌지주스 1L", "개", 2500, 12, 1),
    ]),
]


def seed_company_ids(db: Session) -> list[int]:
    """이메일이 @seed.local 로 끝나는 사용자가 있는 회사 = 시드 회사."""
    return list(db.scalars(select(User.company_id).where(User.email.endswith(SEED_DOMAIN)).distinct()))


def clear(db: Session) -> int:
    """시드 회사와 그 회사의 모든 행을 지운다. 다른 표를 가리키는 표부터 차례로 지운다."""
    ids = seed_company_ids(db)  # 지울 회사
    if ids:
        for model in (InventoryMovement, PurchaseOrderItem, PurchaseOrder, Product, Supplier, User):  # 가리키는 쪽부터
            db.execute(delete(model).where(model.company_id.in_(ids)))  # 그 회사 행 전부
        db.execute(delete(Company).where(Company.id.in_(ids)))  # 마지막에 회사
    db.commit()  # 확정
    return len(ids)  # 지운 회사 수


def insert(db: Session) -> None:
    """회사 2곳에 관리자·담당자 1명씩, 공급업체 2개, 품목 5개를 넣는다."""
    password_hash = hash_password(SEED_PASSWORD)  # 네 계정이 같은 비밀번호 (해시 한 번만 계산)
    for company_name, prefix, suppliers, products in COMPANIES:
        company = Company(name=company_name)  # 회사
        db.add(company)
        db.flush()  # company.id 생성
        for role in ("ADMIN", "STAFF"):  # 관리자, 담당자
            db.add(User(company_id=company.id, name=f"{prefix}-{role.lower()}", role=role,
                        email=f"{role.lower()}.{prefix}{SEED_DOMAIN}",  # 예) admin.gana@seed.local
                        password_hash=password_hash))
        rows = [Supplier(company_id=company.id, name=name, lead_time_days=lead) for name, lead in suppliers]  # 공급업체 2개
        db.add_all(rows)
        db.flush()  # 공급업체 id 생성
        for sku, name, unit, cost, safety, supplier_index in products:  # 품목 5개
            db.add(Product(company_id=company.id, sku=sku, name=name, unit=unit, unit_cost=cost,
                           safety_stock=safety, default_supplier_id=rows[supplier_index].id))
    db.commit()  # 확정


def main() -> None:
    parser = argparse.ArgumentParser(description="개발용 시드 데이터 넣기·지우기")  # 명령줄 설명
    parser.add_argument("--clear", action="store_true", help="시드만 지우고 끝낸다")  # --clear 옵션
    args = parser.parse_args()

    url = make_url(settings.database_url)  # .env 의 DB 주소
    if url.database is None or url.database.endswith("_test"):  # 테스트 DB 에는 절대 넣지 않는다
        raise SystemExit(f"테스트 DB({url.database})에는 시드를 넣지 않습니다. .env 의 DATABASE_URL 을 확인하세요.")
    engine = create_engine(url)  # 개발 DB 연결
    with Session(engine) as db:
        removed = clear(db)  # 넣기 전에도 먼저 지운다 (여러 번 실행해도 같은 결과)
        if args.clear:
            print(f"시드 회사 {removed}곳을 지웠습니다 (DB: {url.database}).")
            return
        insert(db)
        print(f"시드를 넣었습니다 (DB: {url.database}): 회사 2곳, 계정 4개, 공급업체 4개, 품목 10개.")
        print(f"계정: admin.gana / staff.gana / admin.saa / staff.saa {SEED_DOMAIN}, 비밀번호 {SEED_PASSWORD} (개발용)")


if __name__ == "__main__":
    main()
