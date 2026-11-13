"""품목·입고 가져오기(#155) 테스트: 새 품목+입고 한 번에, 재반영 막기, 문제 행, 공급업체 검사, 품목만 모드, 번호 유형 분리."""

import json  # options 글자
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from sqlalchemy import event, func, select  # 쿼리 세기, 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product
from app.schemas.receipt_import import ReceiptImportOptions  # 열 지정
from app.services import receipt_import as service  # 확정 함수를 직접 불러 쿼리를 센다
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


def test_edited_quantity_shows_same_day_warning(client, world, existing, session):
    """번호 열 없이 반영한 줄의 수량을 고쳐 다시 올리면 새 입고로 보이지만, 같은 날·같은 품목 입고가 있다고 경고한다."""
    login_as(client)
    assert post(client, "", csv_file(f"{day(3)},OLD-1,,,,50,"), world).status_code == 201
    preview = post(client, "/preview", csv_file(f"{day(3)},OLD-1,,,,55,", f"{day(2)},OLD-1,,,,5,"), world).json()["data"]
    assert preview["apply_count"] == 2  # 막지는 않는다 (같은 날 정말 두 번 들어올 수도 있다)
    assert [(w["sku"], w["date"], w["existing_quantity"]) for w in preview["warnings"]] == [("OLD-1", day(3), 50)]



def test_commit_result_is_fixed(client, world, existing, session):
    """#222 결과 고정: 확정 경로를 바꿔도 응답·생긴 품목·이력(id 순서)·재고가 한 글자도 달라지면 안 된다.

    새 품목과 기존 품목, 같은 품목 여러 날짜, 같은 내용 두 줄(번호 1·2), 이미 반영된 줄, 문제 행 3종,
    다른 회사에만 있는 SKU(우리 회사에 새 품목으로 생긴다)를 한 파일에 넣는다.
    """
    login_as(client)
    session.add(Product(company_id=world["b_company"].id, sku="B-ONLY", name="B", unit="개", unit_cost=1,
                        default_supplier_id=world["b_supplier"].id))
    session.commit()
    assert post(client, "", csv_file(f"{day(4)},OLD-1,,,,9,"), world).status_code == 201  # 먼저 반영 → OLD-1 재고 9
    content = csv_file(
        f"{day(3)},NEW-1,새1,개,100,30,5",   # 2행: 새 품목 + 입고
        f"{day(2)},NEW-2,새2,개,200,7,",     # 3행: 새 품목(안전재고 비면 0) + 입고
        f"{day(2)},new-1,,,,20,",            # 4행: 같은 새 품목 둘째 줄 (소문자도 같은 SKU)
        f"{day(3)},OLD-1,,,,4,",             # 5행: 기존 품목
        f"{day(1)},OLD-1,,,,5,",             # 6행: 같은 내용 두 줄 → 번호 …|1
        f"{day(1)},OLD-1,,,,5,",             # 7행:                  → 번호 …|2
        f"{day(4)},OLD-1,,,,9,",             # 8행: 이미 반영된 줄 → 건너뜀
        f"{day(1)},OLD-1,,,,0,",             # 9행: 수량 0 → 문제
        f"{day(-1)},NEW-2,,,,1,",            # 10행: 미래 날짜 → 문제
        f"{day(1)},BAD-1,,개,100,5,",        # 11행: 새 품목 이름 없음 → 문제
        f"{day(1)},B-ONLY,B복제,개,10,2,",   # 12행: 다른 회사에만 있는 SKU → 우리 회사 새 품목
        f"{day(1)},NEW-1,,,,1,",             # 13행: 같은 새 품목 셋째 줄
    )
    problems = [
        {"row": 9, "reason": "INVALID_QUANTITY", "message": "수량이 1 이상의 정수가 아닙니다.", "sku": "OLD-1"},
        {"row": 10, "reason": "FUTURE_DATE", "message": "오늘 이후 날짜입니다.", "sku": "NEW-2"},
        {"row": 11, "reason": "INVALID_PRODUCT_INFO",
         "message": "새 품목인데 품목명·단위·단가(0 이상 정수)·안전재고 값이 비었거나 올바르지 않습니다.", "sku": "BAD-1"},
    ]
    skipped = [{"reason": "ALREADY_IMPORTED", "message": "이미 반영된 입고", "count": 1}]
    assert post(client, "/preview", content, world).json() == {"data": {
        "total_rows": 12, "apply_count": 8, "new_product_count": 3,
        "new_products": [
            {"row": 2, "sku": "NEW-1", "name": "새1", "unit": "개", "unit_cost": 100, "safety_stock": 5},
            {"row": 3, "sku": "NEW-2", "name": "새2", "unit": "개", "unit_cost": 200, "safety_stock": 0},
            {"row": 12, "sku": "B-ONLY", "name": "B복제", "unit": "개", "unit_cost": 10, "safety_stock": 0},
        ],
        "skipped": skipped, "skipped_count": 1, "date_from": day(3), "date_to": day(1), "total_quantity": 74,
        "problem_count": 3, "problems": problems, "warnings": []}}

    blocked = post(client, "", content, world)
    assert (blocked.status_code, blocked.json()) == (409, {"error": {
        "code": "IMPORT_HAS_PROBLEMS", "message": "문제 행이 3건 있어 반영할 수 없습니다.", "details": {"problem_count": 3}}})
    assert set(products_of(session, world["a_company"])) == {"OLD-1"}  # 막히면 품목도 생기지 않는다

    done = post(client, "", content, world, exclude_problems=True)
    assert (done.status_code, done.json()) == (201, {"data": {
        "created_product_count": 3, "imported_count": 8, "total_quantity": 74,
        "date_from": day(3), "date_to": day(1), "skipped_count": 1, "problem_count": 3}})

    mine = products_of(session, world["a_company"])
    assert {s: (p.name, p.unit, p.unit_cost, p.safety_stock, p.default_supplier_id, p.is_active) for s, p in mine.items()} == {
        "OLD-1": ("기존", "개", 500, 0, world["a_supplier"].id, True),
        "NEW-1": ("새1", "개", 100, 5, world["a_supplier"].id, True),
        "NEW-2": ("새2", "개", 200, 0, world["a_supplier"].id, True),
        "B-ONLY": ("B복제", "개", 10, 0, world["a_supplier"].id, True),
    }
    sku_of = {p.id: s for s, p in mine.items()}
    made = session.execute(
        select(InventoryMovement.product_id, InventoryMovement.quantity, InventoryMovement.movement_date,
               InventoryMovement.movement_type, InventoryMovement.direction, InventoryMovement.external_ref,
               InventoryMovement.created_by, InventoryMovement.purchase_order_item_id, InventoryMovement.sales_channel)
        .where(InventoryMovement.company_id == world["a_company"].id).order_by(InventoryMovement.id)).all()  # id 순서 = 저장 순서
    staff = world["a_staff"].id  # login_as 기본 사용자
    got = [(sku_of[m[0]], m[1], m[2].isoformat()) + tuple(m[3:]) for m in made]
    assert got == [
        ("OLD-1", 9, day(4), "RECEIPT", "IN", f"{day(4)}|OLD-1|9|1", staff, None, None),  # 먼저 반영한 줄
        ("NEW-1", 30, day(3), "RECEIPT", "IN", f"{day(3)}|NEW-1|30|1", staff, None, None),  # (날짜, 행 번호) 순서
        ("OLD-1", 4, day(3), "RECEIPT", "IN", f"{day(3)}|OLD-1|4|1", staff, None, None),
        ("NEW-2", 7, day(2), "RECEIPT", "IN", f"{day(2)}|NEW-2|7|1", staff, None, None),
        ("NEW-1", 20, day(2), "RECEIPT", "IN", f"{day(2)}|NEW-1|20|1", staff, None, None),
        ("OLD-1", 5, day(1), "RECEIPT", "IN", f"{day(1)}|OLD-1|5|1", staff, None, None),
        ("OLD-1", 5, day(1), "RECEIPT", "IN", f"{day(1)}|OLD-1|5|2", staff, None, None),
        ("B-ONLY", 2, day(1), "RECEIPT", "IN", f"{day(1)}|B-ONLY|2|1", staff, None, None),
        ("NEW-1", 1, day(1), "RECEIPT", "IN", f"{day(1)}|NEW-1|1|1", staff, None, None),
    ]
    assert {s: stock(session, world["a_company"], s) for s in mine} == {"OLD-1": 23, "NEW-1": 51, "NEW-2": 7, "B-ONLY": 2}
    b_only = products_of(session, world["b_company"])["B-ONLY"]
    assert b_only.name == "B" and stock(session, world["b_company"], "B-ONLY") == 0  # 다른 회사 품목은 그대로
    assert session.scalar(select(func.count()).select_from(InventoryMovement)
                          .where(InventoryMovement.company_id == world["b_company"].id)) == 0


def test_commit_query_count_does_not_grow_with_rows(engine, world, existing, session):
    """#222 확정 쿼리 수는 행 수·새 품목 수와 상관없다 (이전에는 입고 줄마다 3개).

    기존 품목만 10행·300행이 같고, 새 품목 1개·50개가 섞여도 같으며, 모두 15개 이하.
    """
    company, user = world["a_company"].id, world["a_staff"].id  # 측정 전에 꺼내 둔다 (만료된 객체 지연 조회 방지)
    opts = ReceiptImportOptions(**COLS, default_supplier_id=world["a_supplier"].id)
    files = {
        "기존 10행": csv_file(*[f"{day(1)},OLD-1,,,,{1 + i}," for i in range(10)]),
        "기존 300행": csv_file(*[f"{day(2)},OLD-1,,,,{1 + i}," for i in range(300)]),
        "새 품목 1개": csv_file(f"{day(3)},OLD-1,,,,1,", f"{day(3)},Q-1,새것,개,100,1,"),
        "새 품목 50개": csv_file(f"{day(4)},OLD-1,,,,1,", *[f"{day(4)},Q-{n},새것,개,100,1," for n in range(100, 150)]),
    }
    counts = {}
    for name, content in files.items():
        statements: list[str] = []

        def listener(conn, cursor, statement, *rest, statements=statements):  # before_cursor_execute
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", listener)
        try:
            assert service.commit(company, session, user, "in.csv", content, opts)["imported_count"] > 0
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        counts[name] = sum(not s.startswith(("SAVEPOINT", "RELEASE")) for s in statements)  # 세이브포인트는 테스트 틀이 넣는 문장
    assert counts["기존 10행"] == counts["기존 300행"], counts
    assert counts["새 품목 1개"] == counts["새 품목 50개"], counts
    assert max(counts.values()) <= 15, counts
    assert stock(session, world["a_company"], "OLD-1") == sum(range(1, 11)) + sum(range(1, 301)) + 2
