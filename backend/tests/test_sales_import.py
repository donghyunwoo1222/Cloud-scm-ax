"""판매 가져오기(#154) 테스트: 열 확인·미리보기·반영, 중복·음수·상태 거르기·회사 분리, 동시 반영."""

import io  # 메모리 위의 파일
import json  # options 글자
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from openpyxl import Workbook  # 엑셀 테스트 파일 만들기
from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 업무 오류
from app.models import InventoryMovement, Product
from app.schemas.sales_import import SalesImportOptions
from app.services import sales_import as service
from app.services import stock as stock_service  # 재고 계산
from tests.concurrency import run_at_once, run_in_new_session
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/sales-imports"
HEADER = "주문번호,주문일시,상태,상품코드,옵션,수량,수취인\n"  # 쇼핑몰 형식이 아닌 임의의 열 구성 (수취인 열은 읽히면 안 된다)
OPTS = {"product_col": 3, "quantity_col": 5, "date_col": 1, "ref_col": 0}  # 위 머리글에서 각 열 번호


def days_ago(n: int) -> str:
    return (seoul_today() - timedelta(days=n)).isoformat()


def csv_file(*lines: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(lines) + "\n").encode("utf-8-sig")  # BOM 포함 UTF-8


def row(ref, day, status, sku, qty, option="", name="홍길동") -> str:
    return f"{ref},{day},{status},{sku},{option},{qty},{name}"


@pytest.fixture
def goods(world, session):
    """회사 A 품목 A-1(재고 10)과 회사 B 품목 B-1(재고 10)."""
    out = {}
    for key, sku in (("a", "A-1"), ("b", "B-1")):
        p = Product(company_id=world[f"{key}_company"].id, sku=sku, name="품목", unit="개", unit_cost=1000,
                    default_supplier_id=world[f"{key}_supplier"].id)
        session.add(p)
        session.flush()
        stock_service.register_movement(
            world[f"{key}_company"].id, session, world[f"{key}_admin"].id, product_id=p.id,
            movement_type="RECEIPT", direction="IN", quantity=10, movement_date=seoul_today() - timedelta(days=30))
        out[key] = p
    session.commit()
    return out


def post(client, path, content, filename="orders.csv", **opts):
    options = {**OPTS, "sales_channel": "SMARTSTORE", **opts}
    return client.post(f"{URL}{path}", files={"file": (filename, content)}, data={"options": json.dumps(options)})


def stock(session, company, product):
    return stock_service.current_stock(company.id, session, product.id)


def test_preview_then_commit_creates_sales_and_reduces_stock(client, world, goods, session):
    """완료 기준: 열을 지정해 올리면 미리보기가 나오고, 확인하면 SALE 이력이 생기며 현재고가 줄어든다."""
    login_as(client)
    content = csv_file(row("O1", days_ago(3), "배송완료", "a-1", 2), row("O2", days_ago(1), "배송완료", "A-1", 3))
    preview = post(client, "/preview", content).json()["data"]
    assert (preview["apply_count"], preview["problem_count"], preview["total_quantity"]) == (2, 0, 5)
    assert preview["date_from"] == days_ago(3) and preview["date_to"] == days_ago(1)
    assert stock(session, world["a_company"], goods["a"]) == 10  # 미리보기는 아무것도 쓰지 않는다

    response = post(client, "", content)
    assert response.status_code == 201 and response.json()["data"]["imported_count"] == 2
    assert stock(session, world["a_company"], goods["a"]) == 5  # 10 - 2 - 3
    sale = session.scalars(select(InventoryMovement).where(InventoryMovement.external_ref == "O1")).one()
    assert (sale.movement_type, sale.sales_channel, sale.movement_date.isoformat()) == ("SALE", "SMARTSTORE", days_ago(3))


def test_same_file_twice_does_not_reduce_stock_twice(client, world, goods, session):
    """완료 기준: 같은 파일을 두 번 올려도 재고가 두 번 줄지 않는다 (두 번째는 모두 건너뜀)."""
    login_as(client)
    content = csv_file(row("O1", days_ago(2), "x", "A-1", 4))
    assert post(client, "", content).status_code == 201
    second = post(client, "/preview", content).json()["data"]
    assert second["apply_count"] == 0 and second["skipped"] == [
        {"reason": "ALREADY_IMPORTED", "message": "이미 반영된 주문번호", "count": 1}]
    assert post(client, "", content).status_code == 409  # 반영할 행이 없다
    assert stock(session, world["a_company"], goods["a"]) == 6


def test_problem_rows_block_commit_unless_excluded(client, world, goods, session):
    """미등록 SKU·다른 회사 SKU·날짜순 음수는 문제 행. 기본은 반영 불가, 제외 체크 시 나머지만 반영."""
    login_as(client)
    content = csv_file(
        row("O1", days_ago(5), "x", "A-1", 6),   # 10-6=4 통과
        row("O2", days_ago(4), "x", "A-1", 7),   # 4-7 < 0 → 문제
        row("O3", days_ago(3), "x", "NOPE", 1),  # 미등록
        row("O4", days_ago(3), "x", "B-1", 1),   # 회사 B 의 SKU → 우리 회사엔 없다
        row("O5", days_ago(2), "x", "A-1", 4),   # 문제 행은 재고를 안 쓴 것으로 치므로 4-4=0 통과
    )
    preview = post(client, "/preview", content).json()["data"]
    assert preview["apply_count"] == 2 and preview["problem_count"] == 3
    assert {(p["row"], p["reason"]) for p in preview["problems"]} == {
        (3, "INSUFFICIENT_STOCK"), (4, "UNKNOWN_SKU"), (5, "UNKNOWN_SKU")}  # 행 번호는 머리글이 1줄

    blocked = post(client, "", content)
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "IMPORT_HAS_PROBLEMS"
    assert stock(session, world["a_company"], goods["a"]) == 10  # 아무것도 쓰지 않았다
    assert stock(session, world["b_company"], goods["b"]) == 10  # 다른 회사는 그대로

    ok = post(client, "", content, exclude_problems=True)
    assert ok.status_code == 201 and ok.json()["data"]["imported_count"] == 2
    assert stock(session, world["a_company"], goods["a"]) == 0


def test_status_filter(client, world, goods):
    """상태 열을 지정하면 고른 값만 반영하고 나머지는 사유와 함께 건너뛴다. 상태 열이 없으면 모두 반영."""
    login_as(client)
    content = csv_file(row("O1", days_ago(2), "배송완료", "A-1", 1), row("O2", days_ago(2), "신규", "A-1", 1),
                       row("O3", days_ago(2), "취소", "A-1", 1))
    p = post(client, "/preview", content, status_col=2, statuses=["배송완료"]).json()["data"]
    assert p["apply_count"] == 1 and p["skipped_count"] == 2 and p["skipped"][0]["reason"] == "STATUS_NOT_SELECTED"
    assert post(client, "/preview", content).json()["data"]["apply_count"] == 3  # 상태 열 없음


def test_row_value_problems(client, world, goods):
    """수량·날짜·주문번호가 이상한 행과 파일 안 주문번호 중복은 문제 행이다. 옵션이 섞이면 경고."""
    login_as(client)
    content = csv_file(
        row("O1", days_ago(2), "x", "A-1", "0"), row("O2", days_ago(2), "x", "A-1", "abc"),
        row("O3", "어제", "x", "A-1", 1), row("O4", "2999-01-01", "x", "A-1", 1),
        row("", days_ago(2), "x", "A-1", 1), row("O6", days_ago(2), "x", "A-1", 1, "흰색"),
        row("O6", days_ago(2), "x", "A-1", 1, "검정"), row("O7", days_ago(2), "x", "A-1", 1, "검정"),
    )
    p = post(client, "/preview", content, option_col=4).json()["data"]
    assert [x["reason"] for x in p["problems"]] == [
        "INVALID_QUANTITY", "INVALID_QUANTITY", "INVALID_DATE", "FUTURE_DATE", "MISSING_REF", "DUPLICATE_REF_IN_FILE"]
    assert p["apply_count"] == 2  # O6(첫 줄)·O7
    assert p["warnings"][0]["sku"] == "A-1" and p["warnings"][0]["option_count"] == 2


def test_xlsx_and_cp949_csv(client, world, goods):
    """.xlsx(날짜 칸·정수형 수량 포함)와 CP949 CSV 도 읽는다. 엑셀이 아닌 파일은 422."""
    login_as(client)
    wb = Workbook()
    ws = wb.active
    ws.append(["주문번호", "주문일시", "상태", "상품코드", "옵션", "수량", "수취인"])
    ws.append(["X1", seoul_today() - timedelta(days=1), "x", "A-1", "", 2.0, "홍길동"])  # 날짜 셀·실수 수량
    buf = io.BytesIO()
    wb.save(buf)
    assert post(client, "/preview", buf.getvalue(), filename="o.xlsx").json()["data"]["apply_count"] == 1
    cp949 = (HEADER + row("C1", days_ago(1), "x", "A-1", 1) + "\n").encode("cp949")
    assert post(client, "/preview", cp949).json()["data"]["apply_count"] == 1
    assert post(client, "/preview", b"not a zip", filename="o.xlsx").status_code == 422
    assert post(client, "/preview", b"x", filename="o.pdf").status_code == 422


def test_limits(client, world, goods):
    """행 5,000개·파일 5MB 를 넘으면 422."""
    login_as(client)
    many = csv_file(*[row(f"R{i}", days_ago(1), "x", "A-1", 1) for i in range(5001)])
    assert post(client, "/preview", many).json()["error"]["code"] == "TOO_MANY_ROWS"
    big = b"a" * (5 * 1024 * 1024 + 1)
    assert post(client, "/preview", big).json()["error"]["code"] == "FILE_TOO_LARGE"


def test_inspect_hints_and_status_values_only_for_chosen_column(client, world, goods):
    """inspect: 머리글 기준 미리 선택 + 고른 상태 열의 값만 돌려준다 (수취인 열 값은 어디에도 없다)."""
    login_as(client)
    content = csv_file(row("O1", days_ago(1), "배송완료", "A-1", 1), row("O2", days_ago(1), "배송완료", "A-1", 1),
                       row("O3", days_ago(1), "신규", "A-1", 1))
    files = {"file": ("o.csv", content)}
    data = client.post(f"{URL}/inspect", files=files, data={"status_col": "2"}).json()["data"]
    assert data["suggested"] == {"product_col": 3, "quantity_col": 5, "date_col": 1, "ref_col": 0, "status_col": 2, "option_col": 4}
    assert data["status_values"] == [{"value": "배송완료", "count": 2}, {"value": "신규", "count": 1}]
    assert "홍길동" not in json.dumps(data, ensure_ascii=False)
    assert client.post(f"{URL}/inspect", files=files).json()["data"]["status_values"] is None


def test_validation_and_auth(client, world, goods):
    """로그인 필요, 판매 채널 필수(반영), 열 번호 검사."""
    content = csv_file(row("O1", days_ago(1), "x", "A-1", 1))
    assert post(client, "/preview", content).status_code == 401
    login_as(client)
    no_channel = client.post(URL, files={"file": ("o.csv", content)}, data={"options": json.dumps(OPTS)})
    assert no_channel.status_code == 422
    assert post(client, "/preview", content, product_col=99).status_code == 422  # 없는 열
    assert post(client, "/preview", content, quantity_col=3).status_code == 422  # 열 겹침
    assert post(client, "/preview", content, nope=1).status_code == 422  # 모르는 칸


def test_other_company_sku_never_imported(client, world, goods, session):
    """회사 B 로 올리면 B 의 SKU 만 반영되고 A 의 재고는 그대로다 (company_id 는 토큰에서만)."""
    login_as(client, "admin@b.test")
    assert post(client, "", csv_file(row("O1", days_ago(1), "x", "B-1", 2))).status_code == 201
    a_sku = post(client, "/preview", csv_file(row("O2", days_ago(1), "x", "A-1", 2))).json()["data"]
    assert a_sku["problems"][0]["reason"] == "UNKNOWN_SKU"
    assert stock(session, world["a_company"], goods["a"]) == 10 and stock(session, world["b_company"], goods["b"]) == 8


def test_concurrent_same_file_imports_once(engine, committed_company):
    """같은 파일을 같은 순간 두 번 반영해도 한 번만 들어간다 (품목 잠금 → 다시 계산 → 이미 반영됨)."""
    data = committed_company
    run_in_new_session(engine, lambda s: stock_service.register_movement(
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="RECEIPT",
        direction="IN", quantity=10, movement_date=seoul_today() - timedelta(days=9)))
    content = csv_file(row("C1", days_ago(1), "x", "CC-1", 4))
    opts = SalesImportOptions(**OPTS, sales_channel="OWN_MALL")
    results = run_at_once(*[lambda: run_in_new_session(
        engine, lambda s: service.commit(data["company_id"], s, data["admin_id"], "o.csv", content, opts)) for _ in range(2)])
    assert sum(not isinstance(r, Exception) for r in results) == 1
    assert all(isinstance(r, AppError) and r.code == "NOTHING_TO_IMPORT" for r in results if isinstance(r, Exception))
    final = run_in_new_session(engine, lambda s: (
        stock_service.current_stock(data["company_id"], s, data["product_id"]),
        s.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.external_ref == "C1"))))
    assert final == (6, 1)


def test_commit_result_is_fixed(client, world, goods, session):
    """#211 결과 고정: 확정 경로를 바꿔도 응답·생긴 이력·id 순서·재고가 한 글자도 달라지면 안 된다.

    같은 품목 여러 줄, 날짜순 재고 부족, 미등록 SKU, 파일 안 번호 중복, 상태 거르기, 이미 반영된 번호, 잘못된 수량, 옵션 섞임을 한 파일에 넣는다.
    """
    login_as(client)
    a1 = goods["a"]  # 재고 10
    a2 = Product(company_id=world["a_company"].id, sku="A-2", name="품목2", unit="개", unit_cost=1000,
                 default_supplier_id=world["a_supplier"].id)
    session.add(a2)
    session.flush()
    stock_service.register_movement(world["a_company"].id, session, world["a_admin"].id, product_id=a2.id,
                                    movement_type="RECEIPT", direction="IN", quantity=5, movement_date=seoul_today() - timedelta(days=30))
    session.commit()
    assert post(client, "", csv_file(row("OLD", days_ago(6), "배송완료", "A-2", 1))).status_code == 201  # 먼저 반영 → A-2 재고 4
    content = csv_file(
        row("O1", days_ago(5), "배송완료", "A-1", 6),               # 2행: 10-6=4 반영
        row("O2", days_ago(4), "배송완료", "A-1", 7),               # 3행: 4-7<0 재고 부족
        row("O3", days_ago(3), "배송완료", "NOPE", 1),              # 4행: 미등록
        row("O1", days_ago(3), "배송완료", "A-2", 1),               # 5행: 파일 안 번호 중복
        row("O5", days_ago(1), "배송완료", "a-2", 2, "빨강"),       # 6행: 4-2=2 반영 (날짜가 가장 늦다)
        row("O6", days_ago(2), "배송완료", "A-1", 4),               # 7행: 4-4=0 반영
        row("O7", days_ago(2), "취소", "A-1", 1),                   # 8행: 고르지 않은 상태
        row("OLD", days_ago(2), "배송완료", "A-2", 1, "파랑"),      # 9행: 이미 반영된 번호
        row("O8", days_ago(2), "배송완료", "A-2", 0),               # 10행: 수량 0
    )
    opts = {"status_col": 2, "statuses": ["배송완료"], "option_col": 4}
    problems = [
        {"row": 3, "reason": "INSUFFICIENT_STOCK", "message": "날짜순으로 적용하면 재고가 부족해집니다.", "sku": "A-1"},
        {"row": 4, "reason": "UNKNOWN_SKU", "message": "등록되지 않은 상품 코드(SKU)입니다.", "sku": "NOPE"},
        {"row": 5, "reason": "DUPLICATE_REF_IN_FILE", "message": "파일 안에서 주문번호가 앞의 행과 겹칩니다.", "sku": "A-2"},
        {"row": 10, "reason": "INVALID_QUANTITY", "message": "수량이 1 이상의 정수가 아닙니다.", "sku": "A-2"},
    ]
    skipped = [{"reason": "STATUS_NOT_SELECTED", "message": "반영하기로 고르지 않은 상태", "count": 1},
               {"reason": "ALREADY_IMPORTED", "message": "이미 반영된 주문번호", "count": 1}]
    assert post(client, "/preview", content, **opts).json() == {"data": {
        "total_rows": 9, "apply_count": 3, "skipped": skipped, "skipped_count": 2,
        "date_from": days_ago(5), "date_to": days_ago(1), "total_quantity": 12, "problem_count": 4, "problems": problems,
        "warnings": [{"sku": "A-2", "option_count": 2, "message": "A-2: 옵션 2종이 하나의 SKU로 합산됩니다."}]}}

    blocked = post(client, "", content, **opts)
    assert (blocked.status_code, blocked.json()) == (409, {"error": {
        "code": "IMPORT_HAS_PROBLEMS", "message": "문제 행이 4건 있어 반영할 수 없습니다.", "details": {"problem_count": 4}}})

    done = post(client, "", content, exclude_problems=True, **opts)
    assert (done.status_code, done.json()) == (201, {"data": {
        "imported_count": 3, "skipped": skipped, "skipped_count": 2, "problem_count": 4,
        "date_from": days_ago(5), "date_to": days_ago(1), "total_quantity": 12}})
    made = session.execute(
        select(InventoryMovement.external_ref, InventoryMovement.product_id, InventoryMovement.quantity,
               InventoryMovement.movement_date, InventoryMovement.movement_type, InventoryMovement.direction,
               InventoryMovement.sales_channel, InventoryMovement.created_by)
        .where(InventoryMovement.company_id == world["a_company"].id, InventoryMovement.external_ref.is_not(None))
        .order_by(InventoryMovement.id)).all()  # id 순서 = 저장 순서
    staff = world["a_staff"].id  # login_as 기본 사용자
    assert [tuple(m[:3]) + (m[3].isoformat(),) + tuple(m[4:]) for m in made] == [
        ("OLD", a2.id, 1, days_ago(6), "SALE", "OUT", "SMARTSTORE", staff),
        ("O1", a1.id, 6, days_ago(5), "SALE", "OUT", "SMARTSTORE", staff),  # (날짜, 행 번호) 순서
        ("O6", a1.id, 4, days_ago(2), "SALE", "OUT", "SMARTSTORE", staff),
        ("O5", a2.id, 2, days_ago(1), "SALE", "OUT", "SMARTSTORE", staff),
    ]
    assert (stock(session, world["a_company"], a1), stock(session, world["a_company"], a2)) == (0, 2)
