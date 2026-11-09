"""품목·입고 가져오기(#155) 테스트: 새 품목+입고 한 번에, 재반영 막기, 문제 행, 공급업체 검사, 품목만 모드, 번호 유형 분리."""

import json  # options 글자
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product
from app.services import stock as stock_service  # 재고 계산
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/receipt-imports"
HEADER = "입고일,상품코드,품목명,단위,단가,수량,안전재고\n"
COLS = {"date_col": 0, "product_col": 1, "name_col": 2, "unit_col": 3, "cost_col": 4, "quantity_col": 5, "safety_col": 6}


def day(n: int) -> str:
    return (seoul_today() - timedelta(days=n)).isoformat()


def csv_file(*lines: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(lines) + "\n").encode("utf-8-sig")


@pytest.fixture
def existing(world, session):
    """회사 A 의 기존 품목 OLD-1 (재고 0)."""
    p = Product(company_id=world["a_company"].id, sku="OLD-1", name="기존", unit="개", unit_cost=500,
                default_supplier_id=world["a_supplier"].id)
    session.add(p)
    session.commit()
    return p


def post(client, path, content, world, **opts):
    options = {**COLS, "default_supplier_id": world["a_supplier"].id, **opts}
    return client.post(f"{URL}{path}", files={"file": ("in.csv", content)}, data={"options": json.dumps(options)})


def products_of(session, company):
    return {p.sku: p for p in session.scalars(select(Product).where(Product.company_id == company.id))}


def stock(session, company, sku):
    return stock_service.current_stock(company.id, session, products_of(session, company)[sku].id)


def test_new_and_existing_skus_in_one_file(client, world, existing, session):
    """완료 기준: 새 SKU·기존 SKU 가 섞인 파일 → 미리보기 "새 품목 N개 + 입고 M건", 반영 한 번에 품목이 생기고 재고가 는다."""
    login_as(client)
    content = csv_file(f"{day(2)},new-1,새 품목,개,\"1,200\",30,5", f"{day(1)},OLD-1,,,,10,", f"{day(1)},NEW-1,,,,20,")
    preview = post(client, "/preview", content, world).json()["data"]
    assert (preview["new_product_count"], preview["apply_count"], preview["total_quantity"], preview["problem_count"]) == (1, 3, 60, 0)
    assert preview["new_products"][0] == {"row": 2, "sku": "NEW-1", "name": "새 품목", "unit": "개", "unit_cost": 1200, "safety_stock": 5}
    assert "NEW-1" not in products_of(session, world["a_company"])  # 미리보기는 쓰지 않는다

    done = post(client, "", content, world)
    assert done.status_code == 201 and done.json()["data"]["created_product_count"] == 1
    new = products_of(session, world["a_company"])["NEW-1"]
    assert (new.default_supplier_id, new.safety_stock, new.is_active) == (world["a_supplier"].id, 5, True)
    assert stock(session, world["a_company"], "NEW-1") == 50 and stock(session, world["a_company"], "OLD-1") == 10


def test_same_file_twice_without_ref_column(client, world, existing, session):
    """완료 기준: 같은 파일을 다시 올려도 품목이 두 번 생기거나 재고가 두 번 늘지 않는다 (번호 열 없음 → 내용으로 번호)."""
    login_as(client)
    content = csv_file(f"{day(1)},OLD-1,,,,10,", f"{day(1)},OLD-1,,,,10,", f"{day(1)},NEW-2,새것,개,100,5,")  # 같은 내용 두 행은 1·2번째로 구분
    assert post(client, "", content, world).status_code == 201
    assert stock(session, world["a_company"], "OLD-1") == 20
    # 행 순서를 바꾸고 한 행을 더해 다시 올려도 기존 세 행은 건너뛰고 새 행만 반영된다
    again = csv_file(f"{day(1)},NEW-2,새것,개,100,5,", f"{day(0)},OLD-1,,,,1,", f"{day(1)},OLD-1,,,,10,", f"{day(1)},OLD-1,,,,10,")
    preview = post(client, "/preview", again, world).json()["data"]
    assert (preview["apply_count"], preview["new_product_count"], preview["skipped_count"]) == (1, 0, 3)
    assert post(client, "", again, world).status_code == 201
    assert stock(session, world["a_company"], "OLD-1") == 21 and stock(session, world["a_company"], "NEW-2") == 5
    assert session.scalar(select(func.count()).select_from(Product).where(Product.sku == "NEW-2")) == 1


def test_ref_column_and_type_separation(client, world, existing, session):
    """번호 열을 쓰면 그 값으로 막는다. 판매 주문번호와 같은 글자여도 입고는 막히지 않는다(유형별 유일)."""
    login_as(client)
    stock_service.register_movement(world["a_company"].id, session, world["a_admin"].id, product_id=existing.id,
                                    movement_type="RECEIPT", direction="IN", quantity=5, movement_date=seoul_today())
    stock_service.register_movement(world["a_company"].id, session, world["a_admin"].id, product_id=existing.id,
                                    movement_type="SALE", direction="OUT", quantity=1, movement_date=seoul_today(),
                                    sales_channel="OTHER", external_ref="1001")
    session.commit()
    content = csv_file(f"1001,{day(1)},OLD-1,3", header="번호,입고일,상품코드,수량\n")
    opts = {"ref_col": 0, "date_col": 1, "product_col": 2, "quantity_col": 3, "name_col": None, "unit_col": None,
            "cost_col": None, "safety_col": None}
    assert post(client, "", content, world, **opts).status_code == 201
    receipt = session.scalars(select(InventoryMovement).where(
        InventoryMovement.external_ref == "1001", InventoryMovement.movement_type == "RECEIPT")).one()
    assert receipt.purchase_order_item_id is None and receipt.quantity == 3  # 발주 없는 직접 입고
    second = post(client, "", content, world, **opts)
    assert second.status_code == 409 and second.json()["error"]["code"] == "NOTHING_TO_IMPORT"


def test_problem_rows(client, world, existing, session):
    """필수 값이 빠진 새 SKU 는 그 SKU 의 모든 행이 문제. 기본은 반영 불가, 제외하면 나머지만 반영."""
    login_as(client)
    content = csv_file(
        f"{day(1)},BAD-1,,개,100,5,",        # 품목명 없음 → 문제
        f"{day(1)},BAD-1,이름,개,100,5,",     # 같은 SKU 의 첫 행이 틀렸으므로 이 행도 문제
        f"{day(1)},BAD-2,이름,개,-1,5,",      # 음수 단가 → 문제
        f"{day(1)},OLD-1,,,,0,",              # 수량 0 → 문제
        f"{day(-1)},OLD-1,,,,1,",             # 미래 날짜 → 문제
        f"{day(1)},OLD-1,,,,7,",              # 정상
    )
    preview = post(client, "/preview", content, world).json()["data"]
    assert {(p["row"], p["reason"]) for p in preview["problems"]} == {
        (2, "INVALID_PRODUCT_INFO"), (3, "INVALID_PRODUCT_INFO"), (4, "INVALID_PRODUCT_INFO"),
        (5, "INVALID_QUANTITY"), (6, "FUTURE_DATE")}
    blocked = post(client, "", content, world)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "IMPORT_HAS_PROBLEMS"
    assert stock(session, world["a_company"], "OLD-1") == 0
    assert post(client, "", content, world, exclude_problems=True).status_code == 201
    assert stock(session, world["a_company"], "OLD-1") == 7 and "BAD-1" not in products_of(session, world["a_company"])


def test_supplier_checks(client, world, existing, session):
    """새 품목이 있으면 공급업체 필수. 다른 회사 업체는 404, 비활성 업체는 409 이고 아무것도 쓰지 않는다."""
    login_as(client)
    content = csv_file(f"{day(1)},NEW-3,새것,개,100,5,")
    assert post(client, "", content, world, default_supplier_id=None).status_code == 422
    assert post(client, "/preview", content, world, default_supplier_id=world["b_supplier"].id).status_code == 404
    assert post(client, "", content, world, default_supplier_id=world["b_supplier"].id).status_code == 404
    world["a_supplier"].is_active = False
    session.commit()
    assert post(client, "", content, world).status_code == 409
    assert "NEW-3" not in products_of(session, world["a_company"])
    # 기존 품목만 입고하는 파일은 공급업체를 고르지 않아도 된다
    assert post(client, "", csv_file(f"{day(1)},OLD-1,,,,2,"), world, default_supplier_id=None).status_code == 201


def test_products_only_mode(client, world, existing, session):
    """수량 열이 없으면 새 품목만 등록. 기존 SKU·같은 SKU 둘째 행은 건너뛰고, 다시 올리면 아무것도 생기지 않는다."""
    login_as(client)
    content = csv_file("P-1,품목1,개,100", "OLD-1,기존 이름 바꾸기,개,999", "P-1,중복,개,1", "B-ONLY,회사B와 같은 SKU,개,0",
                       header="상품코드,품목명,단위,단가\n")
    opts = {"product_col": 0, "name_col": 1, "unit_col": 2, "cost_col": 3, "quantity_col": None, "date_col": None, "safety_col": None}
    session.add(Product(company_id=world["b_company"].id, sku="B-ONLY", name="B", unit="개", unit_cost=1,
                        default_supplier_id=world["b_supplier"].id))
    session.commit()
    preview = post(client, "/preview", content, world, **opts).json()["data"]
    assert (preview["new_product_count"], preview["apply_count"], preview["skipped_count"]) == (2, 0, 2)
    assert post(client, "", content, world, **opts).status_code == 201
    mine = products_of(session, world["a_company"])
    assert mine["P-1"].name == "품목1" and mine["OLD-1"].name == "기존"  # 기존 품목 정보는 고치지 않는다
    assert mine["B-ONLY"].name == "회사B와 같은 SKU" and products_of(session, world["b_company"])["B-ONLY"].name == "B"  # 회사 분리
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == 0  # 입고는 없다
    assert post(client, "", content, world, **opts).json()["error"]["code"] == "NOTHING_TO_IMPORT"


def test_quantity_without_date_column_is_rejected(client, world, existing):
    login_as(client)
    response = post(client, "/preview", csv_file(f"{day(1)},OLD-1,,,,1,"), world, date_col=None)
    assert response.status_code == 422


def test_multiple_suppliers_in_file_is_rejected(client, world, existing, session):
    """공급업체 열을 고르면 새 품목의 업체가 2곳 이상 섞인 파일은 422 로 막는다. 기존 품목 줄의 업체는 보지 않는다."""
    login_as(client)
    header = "입고일,상품코드,품목명,단위,단가,수량,공급업체\n"
    opts = {"date_col": 0, "product_col": 1, "name_col": 2, "unit_col": 3, "cost_col": 4, "quantity_col": 5,
            "safety_col": None, "supplier_col": 6}
    mixed = csv_file(f"{day(1)},N-1,하나,개,1,1,가업체", f"{day(1)},N-2,둘,개,1,1,나업체", header=header)
    for path in ("/preview", ""):
        response = post(client, path, mixed, world, **opts)
        assert response.status_code == 422 and response.json()["error"]["code"] == "MULTIPLE_SUPPLIERS"
    assert "N-1" not in products_of(session, world["a_company"])
    one = csv_file(f"{day(1)},N-1,하나,개,1,1,가업체", f"{day(1)},OLD-1,,,,1,나업체", f"{day(1)},N-2,둘,개,1,1,", header=header)
    assert post(client, "", one, world, **opts).status_code == 201  # 빈 칸·기존 품목 줄은 섞임으로 보지 않는다

