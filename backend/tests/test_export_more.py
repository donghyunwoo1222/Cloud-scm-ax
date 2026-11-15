"""목록 내보내기(#191) 테스트 (PR 2: 재고 현황·입출고 이력·발주서). PR 1(test_export.py)과 같은 항목을 세 대상에 적용한다."""

import csv  # CSV 읽기
import io  # 메모리 위의 파일
import logging  # 로그 확인
import zipfile  # xlsx 안의 시트 XML 보기
from datetime import timedelta  # 며칠 전 날짜

import pytest  # 테스트 도구
from openpyxl import load_workbook  # 내보낸 엑셀 읽기

from app.models import PurchaseOrder, PurchaseOrderItem
from app.services import export, inventory_status
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import (  # 품목·이력·발주 넣기 (같은 헬퍼)
    OLD,
    TODAY,
    add_move,
    add_po,
    add_product,
)

API = "/api/v1"
TEXT = '쉼표,따옴표"줄바꿈\n이모지😀'
INJECTIONS = ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "＝1+1"]
# 대상 → (경로, 머리글, 글자가 그대로 나오는 칸 이름). 칸 이름은 시험이 심은 글자를 확인할 때 쓴다
TARGETS = {
    "stock": (f"{API}/stock/export", export.STOCK_HEADERS, "품목명"),
    "movements": (f"{API}/inventory-movements/export", export.MOVEMENT_HEADERS, "메모"),
    "orders": (f"{API}/purchase-orders/export", export.ORDER_HEADERS, "메모"),
}


@pytest.fixture(autouse=True)
def export_log_on(monkeypatch):
    """alembic 의 fileConfig 가 꺼 둔 로거를 이 파일에서만 다시 켠다 (test_export.py 와 같은 이유)."""
    monkeypatch.setattr(export.log, "disabled", False)


def read_csv(body: bytes) -> list[list[str]]:
    assert body.startswith(b"\xef\xbb\xbf")  # BOM: 엑셀에서 한글이 깨지지 않게
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


def read_xlsx(body: bytes) -> list[tuple]:
    return list(load_workbook(io.BytesIO(body)).worksheets[0].iter_rows(values_only=True))


def get(client, target, fmt="csv", **params):
    """내보내기 요청 → (응답, 머리글 뒤의 줄들 [{칸 이름: 값}])."""
    path, headers, _ = TARGETS[target]
    response = client.get(path, params={"format": fmt, **params})
    if response.status_code != 200:
        return response, []
    table = read_csv(response.content) if fmt == "csv" else read_xlsx(response.content)
    assert list(table[0]) == headers  # 허용한 열만, 순서 그대로
    return response, [dict(zip(headers, r, strict=True)) for r in table[1:]]


def add_order(session, world, number, status, product, qty, key="a", **fields):
    """add_po 와 같되 (발주서, 줄) 을 돌려준다."""
    line = add_po(session, world, number, status, product, qty, key=key, **fields)
    return session.get(PurchaseOrder, line.purchase_order_id), line


def seed(session, world, memo=TEXT, name=TEXT):
    """대상 세 개에 한 줄씩 있는 회사 A 데이터 + 회사 B 데이터. 글자 칸(품목명·메모)에는 memo·name 을 넣는다."""
    for key, label in (("a", "MINE"), ("b", "THEIRS")):
        p = add_product(session, world, label, key=key)
        p.name = name if key == "a" else "남의 품목"
        add_move(session, world, p, "RECEIPT", "IN", 100, OLD, key=key)
        session.flush()
        m = add_move(session, world, p, "SALE", "OUT", 5, 1, key=key)
        m.memo = memo if key == "a" else "남의 메모"
        order, _ = add_order(session, world, f"PO-{label}", "DRAFT", p, 10, key=key)
        order.memo = memo if key == "a" else "남의 메모"
    session.commit()


# ---------- 재고 현황 ----------

def stock_item(session, world, sku, stock, sold=300, key="a", **fields):
    """40일 전 입고 (sold + stock), 어제 판매 sold → 현재고 stock. 일평균 sold/30."""
    p = add_product(session, world, sku, key=key, **fields)
    add_move(session, world, p, "RECEIPT", "IN", sold + stock, OLD, key=key)
    add_move(session, world, p, "SALE", "OUT", sold, 1, key=key)
    return p


def test_stock_same_as_list_across_pages_and_status_computed_once(client, world, session, monkeypatch):
    """상태 필터 결과가 화면 목록과 같고 쪽(3개씩 4번)을 넘어도 전체 품목 상태 계산은 한 번뿐이다."""
    monkeypatch.setattr(export, "CHUNK", 3)
    for i in range(10):  # 현재고 10 → 재주문점 70 이하 → 부족
        stock_item(session, world, f"SHORT-{i:02}", 10)
    stock_item(session, world, "OK-1", 5000)  # 현재고 충분 → 정상
    off = stock_item(session, world, "OFF-1", 10)
    off.is_active = False
    session.commit()
    login_as(client)

    listed = client.get(f"{API}/stock", params={"status": "SHORTAGE", "page_size": 100}).json()["data"]
    calls = []
    real = inventory_status.calculate_for
    monkeypatch.setattr(inventory_status, "calculate_for", lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    _, rows = get(client, "stock", "xlsx", status="SHORTAGE")
    assert [r["SKU"] for r in rows] == [r["sku"] for r in listed] and len(rows) == 10  # 목록과 같은 줄·순서
    assert len(calls) == 1  # 4쪽을 읽어도 계산은 한 번
    assert {r["상태"] for r in rows} == {"부족"} and rows[0]["현재고"] == 10 and rows[0]["재주문점"] == 70.0

    _, everyone = get(client, "stock", "xlsx", include_inactive="true")
    assert len(everyone) == 12 and {r["SKU"]: r["활성"] for r in everyone}["OFF-1"] == "비활성"
    assert {r["SKU"]: r["상태"] for r in everyone}["OFF-1"] is None  # 비활성은 상태 없음


# ---------- 입출고 이력 ----------

def test_movements_filters_pages_correction_and_po_number(client, world, session, monkeypatch):
    monkeypatch.setattr(export, "CHUNK", 4)
    p = add_product(session, world, "MV-1")
    for day in range(10):
        add_move(session, world, p, "RECEIPT", "IN", 10, 30 + day)
    sale = add_move(session, world, p, "SALE", "OUT", 5, 3)
    add_move(session, world, p, "CORRECTION", "IN", 2, 3, reverses=sale.id)  # 판매 5 중 2 정정
    _, line = add_order(session, world, "PO-MV", "ORDERED", p, 10)
    add_move(session, world, p, "RECEIPT", "IN", 4, 2, po_item=line.id)  # 발주 입고 (부분)
    session.commit()
    login_as(client)

    listed = client.get(f"{API}/inventory-movements", params={"page_size": 100}).json()
    _, rows = get(client, "movements", "xlsx")
    assert len(rows) == listed["meta"]["total"] == 13  # 목록 1쪽(20개)과 상관없이 모든 줄, 4개씩 나눠 읽어도 겹침 없음
    assert [r["입출고일"] for r in rows] == sorted((r["입출고일"] for r in rows), reverse=True)  # 입출고일 최신순
    by_type = {r["유형"]: r for r in rows if r["유형"] != "입고"}
    assert (by_type["정정"]["방향"], by_type["정정"]["수량"], by_type["정정"]["사유"]) == ("증가", 2, "사유")
    assert (by_type["판매"]["판매 채널"], by_type["판매"]["단위"], by_type["판매"]["등록자"]) == ("OWN_MALL", "개", "a-STAFF")
    assert [r["발주번호"] for r in rows if r["발주번호"]] == ["PO-MV"]
    assert rows[0]["등록 시각"][:4].isdigit() and len(rows[0]["등록 시각"]) == 16  # 서울 시간 YYYY-MM-DD HH:MM

    def day(n):
        return (TODAY - timedelta(days=n)).isoformat()

    period = {"date_from": day(33), "date_to": day(31)}
    _, ranged = get(client, "movements", **period)
    assert len(ranged) == client.get(f"{API}/inventory-movements", params=period).json()["meta"]["total"] == 3
    _, only_sales = get(client, "movements", "xlsx", movement_type="SALE")
    assert [r["유형"] for r in only_sales] == ["판매"]
    bad = client.get(TARGETS["movements"][0], params={"format": "csv", "date_from": day(1), "date_to": day(5)})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "VALIDATION_ERROR"  # 목록과 같은 422


# ---------- 발주서 ----------

def test_orders_lines_units_partial_receipt_and_filters(client, world, session, monkeypatch):
    monkeypatch.setattr(export, "CHUNK", 2)
    p = add_product(session, world, "PO-P1")
    q = add_product(session, world, "PO-P2")
    # 발주단위 줄: 12개입 BOX 3개 = 36개, BOX 단가 11000 → 금액 33000
    order, box = add_order(session, world, "PO-A1", "ORDERED", p, 36, units_per_box=12, box_unit_price=11000, order_unit="BOX")
    plain = PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id, product_id=q.id, quantity=5, unit_price=1000)
    session.add(plain)
    session.flush()
    receipt = add_move(session, world, p, "RECEIPT", "IN", 24, 2, po_item=box.id)  # 부분 입고 24
    add_move(session, world, p, "CORRECTION", "OUT", 4, 2, po_item=box.id, reverses=receipt.id)  # 정정 4 → 누적 20
    order.approved_by = world["a_admin"].id
    for i in range(4):  # 쪽을 넘기는 다른 발주서들
        add_order(session, world, f"PO-B{i}", "APPROVED", add_product(session, world, f"PO-X{i}"), 1)
    empty = PurchaseOrder(company_id=order.company_id, supplier_id=order.supplier_id, po_number="PO-EMPTY", status="CANCELLED",
                          created_by=world["a_staff"].id)
    session.add(empty)
    session.commit()
    login_as(client)

    _, rows = get(client, "orders", "xlsx")
    assert len(rows) == 2 + 4 + 1  # A1 줄 2 + 다른 발주서 4 + 줄 없는 발주서 1
    a1 = {r["SKU"]: r for r in rows if r["발주번호"] == "PO-A1"}
    assert (a1["PO-P1"]["발주단위 수량"], a1["PO-P1"]["발주단위 이름"], a1["PO-P1"]["환산계수"]) == (3, "BOX", 12)
    assert (a1["PO-P1"]["기본단위 수량"], a1["PO-P1"]["기본단위 이름"], a1["PO-P1"]["단가"]) == (36, "개", 1000)
    assert (a1["PO-P1"]["발주단위 단가"], a1["PO-P1"]["금액"], a1["PO-P1"]["누적 입고량"]) == (11000, 33000, 20)
    assert (a1["PO-P2"]["발주단위 수량"], a1["PO-P2"]["발주단위 이름"], a1["PO-P2"]["환산계수"]) == (None, None, None)  # 발주단위 없는 줄
    assert (a1["PO-P2"]["기본단위 수량"], a1["PO-P2"]["금액"], a1["PO-P2"]["누적 입고량"]) == (5, 5000, 0)
    assert a1["PO-P1"]["승인자"] == "a-ADMIN" and a1["PO-P1"]["작성자"] == "a-STAFF" and a1["PO-P1"]["상태"] == "ORDERED"
    assert a1["PO-P1"]["공급업체"] == "A업체"
    empty_row = next(r for r in rows if r["발주번호"] == "PO-EMPTY")
    assert empty_row["SKU"] is None and empty_row["상태"] == "CANCELLED"
    listed = client.get(f"{API}/purchase-orders", params={"page_size": 100}).json()["data"]
    assert list(dict.fromkeys(r["발주번호"] for r in rows)) == [o["po_number"] for o in listed]  # 목록과 같은 발주서·순서

    _, ordered = get(client, "orders", status="ORDERED")
    assert {r["발주번호"] for r in ordered} == {"PO-A1"} and len(ordered) == 2
    _, searched = get(client, "orders", q="PO-B2")
    assert [r["발주번호"] for r in searched] == ["PO-B2"]


def test_orders_row_cap_counts_lines_not_orders(client, world, session, monkeypatch):
    """발주서는 상한 안(2장)이어도 줄이 상한(3)을 넘으면 파일을 만들기 전에 422."""
    monkeypatch.setattr(export, "MAX_ROWS", 3)
    for n in ("PO-1", "PO-2"):
        order, _ = add_order(session, world, n, "APPROVED", add_product(session, world, f"C-{n}"), 1)
        session.add(PurchaseOrderItem(company_id=order.company_id, purchase_order_id=order.id,
                                      product_id=add_product(session, world, f"D-{n}").id, quantity=1, unit_price=1))
    session.commit()  # 2장, 줄 4개
    login_as(client)
    response = client.get(TARGETS["orders"][0], params={"format": "xlsx"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    assert "4개" in response.json()["error"]["message"]


# ---------- 세 대상 공통 ----------

@pytest.mark.parametrize("target", list(TARGETS))
def test_other_company_never_included(client, world, session, target):
    seed(session, world, memo="우리 글")
    login_as(client)
    for fmt in ("csv", "xlsx"):
        response, rows = get(client, target, fmt, **({"sort": "date"} if target == "movements" else {}))
        assert rows and all(r["SKU" if target != "orders" else "발주번호"] in ("MINE", "PO-MINE") for r in rows)
        assert b"THEIRS" not in response.content and "남의".encode() not in response.content and "B업체".encode() not in response.content


@pytest.mark.parametrize("target", list(TARGETS))
def test_formula_injection_neutralized(client, world, session, target):
    """글자 칸은 CSV 에 ' 가 붙고 xlsx 는 문자열 칸이다. 숫자 칸은 숫자 그대로."""
    for i, bad in enumerate(INJECTIONS):
        p = add_product(session, world, f"INJ-{i}")
        p.name = bad
        m = add_move(session, world, p, "RECEIPT", "IN", 7, OLD)
        m.memo = bad
        order, _ = add_order(session, world, f"PO-INJ-{i}", "APPROVED", p, 7)
        order.memo = bad
    session.commit()
    login_as(client)
    column = TARGETS[target][2]
    _, rows = get(client, target)
    assert {r[column] for r in rows} == {"'" + bad for bad in INJECTIONS}
    number = {"stock": "현재고", "movements": "수량", "orders": "기본단위 수량"}[target]
    assert {r[number] for r in rows} == {"7"}  # 숫자는 글자로 바뀌지 않았다 (CSV 에서는 7, 앞에 ' 없음)

    body = client.get(TARGETS[target][0], params={"format": "xlsx"}).content
    sheet_xml = zipfile.ZipFile(io.BytesIO(body)).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml and "<f " not in sheet_xml  # 수식 칸이 하나도 없다
    ws = load_workbook(io.BytesIO(body)).worksheets[0]
    col = TARGETS[target][1].index(column)
    ncol = TARGETS[target][1].index(number)
    for row in ws.iter_rows(min_row=2):
        assert row[col].data_type == "s" and row[col].value.replace("\n", "\r") in [b.replace("\n", "\r") for b in INJECTIONS]
        assert (row[ncol].value, row[ncol].data_type) == (7, "n")  # 숫자 칸


@pytest.mark.parametrize("target", list(TARGETS))
def test_korean_emoji_and_no_sensitive_columns(client, world, session, target):
    seed(session, world)
    login_as(client)
    for fmt in ("csv", "xlsx"):
        response, rows = get(client, target, fmt)  # get() 이 머리글이 허용 목록과 정확히 같은지 확인한다
        assert rows[0][TARGETS[target][2]] == TEXT
        assert b"@a.test" not in response.content and b"argon2" not in response.content  # 이메일·비밀번호 해시 없음


@pytest.mark.parametrize("target", list(TARGETS))
def test_too_large_bad_format_and_login(client, world, session, monkeypatch, caplog, target):
    monkeypatch.setattr(export, "MAX_ROWS", 0)
    seed(session, world)
    path = TARGETS[target][0]
    assert client.get(path, params={"format": "csv"}).status_code == 401  # 로그인 없음
    login_as(client)
    with caplog.at_level(logging.INFO, logger="app.services.export"):
        too_large = client.get(path, params={"format": "xlsx"})
    assert too_large.status_code == 422 and too_large.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    assert "outcome=TOO_LARGE" in caplog.text
    assert client.get(path, params={"format": "pdf"}).status_code == 422  # 잘못된 형식
    assert client.get(path).status_code == 422  # 형식 없음


@pytest.mark.parametrize("target", list(TARGETS))
def test_both_roles_and_log_line(client, world, session, caplog, target):
    """관리자·담당자 둘 다 가능. 로그는 한 줄: 누가·무엇·몇 행, 내용 없음."""
    seed(session, world, memo="비밀스러운 메모", name="비밀스러운 품목명")
    for email in ("admin@a.test", "staff@a.test"):
        login_as(client, email)
        with caplog.at_level(logging.INFO, logger="app.services.export"):
            caplog.clear()
            response = client.get(TARGETS[target][0], params={"format": "csv"})
        assert response.status_code == 200 and f'filename="{"purchase-orders" if target == "orders" else target}-' in response.headers["content-disposition"]
        records = [r.getMessage() for r in caplog.records if r.name == "app.services.export"]
        expected = 2 if target == "movements" else 1  # 이력은 입고·판매 두 줄
        assert len(records) == 1 and "fmt=csv" in records[0] and f"rows={expected} outcome=OK" in records[0]
        assert "비밀" not in records[0] and "@a.test" not in records[0]


def test_route_declared_before_id_path(client, world, session):
    """/export 가 /{id} 로 읽히지 않는다 (422 가 아니라 200)."""
    login_as(client)
    for target in TARGETS:
        assert client.get(TARGETS[target][0], params={"format": "csv"}).status_code == 200



def test_movement_type_labels_match_screen(client, world, session):
    """유형 라벨은 화면(TYPE_LABEL)과 같다: 조정은 "실사 조정"."""
    p = add_product(session, world, "LB-1")
    add_move(session, world, p, "ADJUSTMENT", "OUT", 1, 1)
    session.commit()
    login_as(client)
    _, rows = get(client, "movements")
    assert [r["유형"] for r in rows] == ["실사 조정"] and rows[0]["방향"] == "감소"
