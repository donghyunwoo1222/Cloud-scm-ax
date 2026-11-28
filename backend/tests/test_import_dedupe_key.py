"""가져오기 중복 키 (#254): 판매·입고 가져오기는 (주문번호, 품목)으로 중복을 판정한다. 주문번호 단독이 아니다."""

import json  # options 글자
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from alembic import command  # 마이그레이션 실행
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, text  # 검사·쿼리
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError  # DB 유일 제한 위반
from sqlalchemy.orm import Session

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import Company, InventoryMovement, Product, Supplier, User
from app.schemas.movements import CorrectionCreate
from app.services import stock as stock_service  # 재고·정정
from tests.conftest import BACKEND_DIR, TEST_DATABASE_URL, reset_database
from tests.helpers import login_as  # 공통 로그인

SALES = "/api/v1/sales-imports"
RECEIPTS = "/api/v1/receipt-imports"
SALES_HEADER = "주문번호,주문일시,상품코드,수량\n"
SALES_OPTS = {"ref_col": 0, "date_col": 1, "product_col": 2, "quantity_col": 3}
RECEIPT_HEADER = "번호,입고일,상품코드,수량\n"
RECEIPT_OPTS = {"ref_col": 0, "date_col": 1, "product_col": 2, "quantity_col": 3, "name_col": None, "unit_col": None,
                "cost_col": None, "safety_col": None}


def days_ago(n: int) -> str:
    return (seoul_today() - timedelta(days=n)).isoformat()


def file_of(header: str, *lines: str) -> bytes:
    return (header + "\n".join(lines) + "\n").encode("utf-8-sig")


@pytest.fixture
def goods(world, session):
    """회사 A 품목 A-1·A-2 (각 재고 10)."""
    out = {}
    for sku in ("A-1", "A-2"):
        p = Product(company_id=world["a_company"].id, sku=sku, name="품목", unit="개", unit_cost=1000,
                    default_supplier_id=world["a_supplier"].id)
        session.add(p)
        session.flush()
        stock_service.register_movement(
            world["a_company"].id, session, world["a_admin"].id, product_id=p.id,
            movement_type="RECEIPT", direction="IN", quantity=10, movement_date=seoul_today() - timedelta(days=30))
        out[sku] = p
    session.commit()
    return out


def sales(client, path, content, channel="SMARTSTORE"):
    options = {**SALES_OPTS, "sales_channel": channel}
    return client.post(f"{SALES}{path}", files={"file": ("o.csv", content)}, data={"options": json.dumps(options)})


def receipts(client, path, content, world):
    options = {**RECEIPT_OPTS, "default_supplier_id": world["a_supplier"].id}
    return client.post(f"{RECEIPTS}{path}", files={"file": ("r.csv", content)}, data={"options": json.dumps(options)})


def stock(session, world, product):
    return stock_service.current_stock(world["a_company"].id, session, product.id)


def skipped_counts(body: dict) -> dict:
    return {s["reason"]: s["count"] for s in body["skipped"]}


# ---------- 판매 가져오기 ----------

def test_sales_same_order_different_sku_both_applied(client, world, goods, session):
    """주문 1건에 품목 2줄(같은 주문번호): 둘 다 반영된다. 예) O1 에 A-1 3개·A-2 4개 → 재고 7·6."""
    login_as(client)
    content = file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3", f"O1,{days_ago(2)},A-2,4")
    preview = sales(client, "/preview", content).json()["data"]
    assert preview["apply_count"] == 2 and preview["problem_count"] == 0 and preview["skipped_count"] == 0
    assert sales(client, "", content).status_code == 201
    assert (stock(session, world, goods["A-1"]), stock(session, world, goods["A-2"])) == (7, 6)
    again = sales(client, "/preview", content).json()["data"]  # 같은 파일을 다시: 두 줄 모두 건너뜀
    assert again["apply_count"] == 0 and skipped_counts(again) == {"ALREADY_IMPORTED": 2}


def test_sales_same_order_same_sku_in_file_is_problem(client, world, goods):
    """같은 파일에서 (주문번호, SKU)가 겹치면 둘째 줄부터 문제 행이다 (합산하지 않는다)."""
    login_as(client)
    content = file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3", f"O1,{days_ago(2)},a-1,4")  # SKU 는 대문자로 비교
    body = sales(client, "/preview", content).json()["data"]
    assert body["apply_count"] == 1 and body["total_quantity"] == 3
    assert [(p["row"], p["reason"]) for p in body["problems"]] == [(3, "DUPLICATE_REF_IN_FILE")]


def test_sales_partial_reupload_applies_only_new_line(client, world, goods, session):
    """이미 반영된 주문(O1/A-1)에 새 줄(O1/A-2)을 더한 파일: 기존 줄은 건너뛰고 새 줄만 반영한다."""
    login_as(client)
    assert sales(client, "", file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3")).status_code == 201
    content = file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3", f"O1,{days_ago(2)},A-2,4")
    response = sales(client, "", content)
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["imported_count"] == 1 and skipped_counts(data) == {"ALREADY_IMPORTED": 1}
    assert (stock(session, world, goods["A-1"]), stock(session, world, goods["A-2"])) == (7, 6)


def test_sales_corrected_sale_reupload_is_skipped(client, world, goods, session):
    """정정이 걸린 SALE 을 같은 파일로 다시 올려도 건너뛴다 (정정은 external_ref 가 비어 있고 원래 SALE 이 번호를 지킨다)."""
    login_as(client)
    content = file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,5")
    assert sales(client, "", content).status_code == 201
    sale = session.scalars(select(InventoryMovement).where(InventoryMovement.external_ref == "O1")).one()
    stock_service.create_correction(world["a_company"].id, session, world["a_admin"].id, sale.id,
                                    CorrectionCreate(quantity=2, reason="수량 잘못 입력"))
    session.commit()
    body = sales(client, "/preview", content).json()["data"]
    assert body["apply_count"] == 0 and skipped_counts(body) == {"ALREADY_IMPORTED": 1}


def test_sales_unknown_sku_with_imported_ref_is_unknown_sku(client, world, goods):
    """이미 반영된 번호(O1)에 미등록 SKU 줄이 오면 건너뜀이 아니라 UNKNOWN_SKU 문제 행이다."""
    login_as(client)
    assert sales(client, "", file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3")).status_code == 201
    body = sales(client, "/preview", file_of(SALES_HEADER, f"O1,{days_ago(2)},NOPE,1")).json()["data"]
    assert [(p["row"], p["reason"]) for p in body["problems"]] == [(2, "UNKNOWN_SKU")]
    assert body["skipped_count"] == 0


def test_sales_other_channel_same_sku_is_skipped(client, world, goods):
    """채널은 키가 아니다: 같은 번호·같은 SKU 를 다른 채널로 올려도 건너뛴다."""
    login_as(client)
    content = file_of(SALES_HEADER, f"O1,{days_ago(2)},A-1,3")
    assert sales(client, "", content, channel="SMARTSTORE").status_code == 201
    body = sales(client, "/preview", content, channel="OWN_MALL").json()["data"]
    assert body["apply_count"] == 0 and skipped_counts(body) == {"ALREADY_IMPORTED": 1}


# ---------- DB 유일 제한 ----------

def test_db_unique_on_ref_and_product(world, goods, session):
    """같은 (회사, 유형, 번호, 품목) 직접 INSERT 는 막히고, 품목이 다르면 같은 번호도 들어간다."""
    cid, uid = world["a_company"].id, world["a_admin"].id

    def add(product):
        stock_service.register_movement(cid, session, uid, product_id=product.id, movement_type="SALE", direction="OUT",
                                        quantity=1, movement_date=seoul_today(), sales_channel="OTHER", external_ref="DUP")
        session.flush()

    add(goods["A-1"])
    add(goods["A-2"])  # 같은 번호·다른 품목: 통과
    with pytest.raises(IntegrityError), session.begin_nested():
        add(goods["A-1"])  # 같은 번호·같은 품목: 유일 제한 위반


# ---------- 입고 가져오기 ----------

def test_receipt_same_ref_different_sku_both_applied_and_partial_reupload(client, world, goods, session):
    """같은 입고 번호에 품목 2줄: 둘 다 반영. 같은 번호에 새 SKU 줄을 더해 다시 올리면 새 줄만 반영된다."""
    login_as(client)
    both = file_of(RECEIPT_HEADER, f"R1,{days_ago(2)},A-1,5", f"R1,{days_ago(2)},A-2,6")
    assert receipts(client, "/preview", both, world).json()["data"]["apply_count"] == 2
    # R1/A-1 만 먼저 반영하고, 같은 번호에 A-2 줄을 더한 파일을 올리면 새 줄만 반영된다
    assert receipts(client, "", file_of(RECEIPT_HEADER, f"R1,{days_ago(2)},A-1,5"), world).status_code == 201
    response = receipts(client, "", both, world)
    assert response.status_code == 201 and response.json()["data"]["imported_count"] == 1
    assert (stock(session, world, goods["A-1"]), stock(session, world, goods["A-2"])) == (15, 16)
    again = receipts(client, "/preview", both, world).json()["data"]
    assert again["apply_count"] == 0 and skipped_counts(again) == {"ALREADY_IMPORTED": 2}


def test_receipt_same_ref_same_sku_in_file_is_problem(client, world, goods):
    login_as(client)
    content = file_of(RECEIPT_HEADER, f"R1,{days_ago(2)},A-1,5", f"R1,{days_ago(2)},A-1,6")
    body = receipts(client, "/preview", content, world).json()["data"]
    assert [(p["row"], p["reason"]) for p in body["problems"]] == [(3, "DUPLICATE_REF_IN_FILE")]


# ---------- 마이그레이션 ----------

def test_migration_up_down_up_and_downgrade_stops_on_conflict():
    """up → down → up 이 되고, 같은 번호에 품목이 둘 이상이면 downgrade 는 이유를 적은 예외로 멈춘다."""
    url = make_url(TEST_DATABASE_URL).set(database="scm_test_dedupe_migration").render_as_string(hide_password=False)
    reset_database(url)  # 이 DB 를 head 까지 올려 둔다 (이 이름은 테스트 DB 이름 규칙에 맞다)
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    eng = create_engine(url)

    def indexes() -> set[str]:
        return {i["name"] for i in inspect(eng).get_indexes("inventory_movements")}

    assert "uq_movements_company_type_ref_product" in indexes()
    assert "uq_movements_company_type_external_ref" not in indexes()
    command.downgrade(cfg, "-1")  # 충돌이 없으면 되돌아간다
    assert "uq_movements_company_type_external_ref" in indexes()
    assert "uq_movements_company_type_ref_product" not in indexes()
    command.upgrade(cfg, "head")
    assert "uq_movements_company_type_ref_product" in indexes()

    with Session(eng) as s:  # 같은 번호·다른 품목 2줄을 만든다
        company = Company(name="마이그레이션상사")
        s.add(company)
        s.flush()
        user = User(company_id=company.id, name="관리자", email="m@mig.test", password_hash="x", role="ADMIN")
        supplier = Supplier(company_id=company.id, name="업체", lead_time_days=3)
        s.add_all([user, supplier])
        s.flush()
        products = [Product(company_id=company.id, sku=f"M-{i}", name="품목", unit="개", unit_cost=1, default_supplier_id=supplier.id)
                    for i in (1, 2)]
        s.add_all(products)
        s.flush()
        for p in products:
            s.add(InventoryMovement(company_id=company.id, product_id=p.id, movement_type="RECEIPT", direction="IN",
                                    quantity=1, external_ref="SAME", created_by=user.id))
        s.commit()
    with pytest.raises(RuntimeError, match="downgrade 불가"):
        command.downgrade(cfg, "-1")
    assert "uq_movements_company_type_ref_product" in indexes()  # 멈춘 뒤에도 새 인덱스가 그대로다
    with eng.begin() as conn:  # 충돌 행을 치우면(테스트 DB 한정) 다시 되돌릴 수 있다
        conn.execute(text("DELETE FROM inventory_movements WHERE id = (SELECT max(id) FROM inventory_movements)"))
    command.downgrade(cfg, "-1")
    assert "uq_movements_company_type_external_ref" in indexes()
    eng.dispose()
