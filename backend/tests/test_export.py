"""목록 내보내기(#191) 테스트 (PR 1: 품목). 필터·전체 행, 회사 분리, 수식 무력화, 한글·특수문자, 민감 열, 가져오기 왕복, 상한·형식·로그인."""

import csv  # CSV 읽기
import io  # 메모리 위의 파일
import json  # 가져오기 options 글자
import logging  # 로그 확인
import zipfile  # xlsx 안의 시트 XML 보기

import pytest  # 테스트 도구
from openpyxl import load_workbook  # 내보낸 엑셀 읽기

from app.db import get_read_db  # 읽기 세션 의존성 (스트리밍 중 세션 수명 확인)
from app.main import app  # 의존성 바꿔 끼우기
from app.models import Product, Supplier
from app.services import export
from app.services import products as products_service
from app.services.import_templates import (
    PRODUCT_HEADERS as TEMPLATE_HEADERS,  # 가져오기 템플릿 머리글 (#189)
)
from app.services.product_import import HINTS  # 품목 가져오기 열 힌트
from app.services.sales_import import _unquote, suggest_columns  # CSV ' 떼기, 열 힌트
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/products/export"
INJECTIONS = ["=1+1", "+1", "-1", "@SUM(A1)", "\t=1", "\r=1", "\n=1", "＝1+1", '=HYPERLINK("http://x","y")']


@pytest.fixture(autouse=True)
def export_log_on(monkeypatch):
    """테스트 DB 를 만들 때 alembic 의 fileConfig 가 이미 만들어진 로거를 꺼 둔다. 이 파일의 로그만 다시 켠다."""
    monkeypatch.setattr(export.log, "disabled", False)


def add(session, company, supplier, sku, name, **kw):
    p = Product(company_id=company.id, sku=sku, name=name, unit=kw.pop("unit", "EA"), unit_cost=kw.pop("unit_cost", 100),
                safety_stock=kw.pop("safety_stock", 0), default_supplier_id=supplier.id, **kw)
    session.add(p)
    return p


def read_csv(body: bytes) -> list[list[str]]:
    assert body.startswith(b"\xef\xbb\xbf")  # BOM: 엑셀에서 한글이 깨지지 않게
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


def read_xlsx(body: bytes) -> list[tuple]:
    return list(load_workbook(io.BytesIO(body)).worksheets[0].iter_rows(values_only=True))


def test_filters_and_all_rows_beyond_page_size(client, world, session, monkeypatch):
    """화면 목록과 같은 조건, 쪽 크기(20)와 상관없이 모든 행. 쪽을 여러 번 읽어도 줄이 빠지거나 겹치지 않는다."""
    monkeypatch.setattr(export, "CHUNK", 7)  # 25행을 7개씩 4번 나눠 읽게 한다
    a, sup = world["a_company"], world["a_supplier"]
    for i in range(25):
        add(session, a, sup, f"KEEP-{i:02}", f"찾을 품목 {i}")
    add(session, a, sup, "OTHER-1", "다른 이름")
    add(session, a, sup, "KEEP-OFF", "찾을 품목 비활성", is_active=False)
    session.commit()
    login_as(client)

    listed = client.get("/api/v1/products", params={"q": "찾을", "page_size": 20}).json()
    rows = read_csv(client.get(URL, params={"format": "csv", "q": "찾을"}).content)
    assert listed["meta"]["total"] == 25 and len(rows) == 1 + 25  # 머리글 + 25행 (목록 1쪽은 20개뿐)
    assert [r[0] for r in rows[1:]] == [f"KEEP-{i:02}" for i in reversed(range(25))]  # 목록과 같은 최신순, 겹침 없음
    with_off = read_csv(client.get(URL, params={"format": "csv", "q": "찾을", "include_inactive": "true"}).content)
    assert len(with_off) == 1 + 26 and ["KEEP-OFF", "비활성"] == [with_off[1][0], with_off[1][-1]]
    xlsx = read_xlsx(client.get(URL, params={"format": "xlsx", "q": "찾을"}).content)
    assert len(xlsx) == 1 + 25 and xlsx[0] == tuple(export.PRODUCT_HEADERS)


def test_streaming_keeps_read_session_open(client, world, session, monkeypatch):
    """확인 못함 1: CSV 를 보내는 동안(2쪽부터 읽을 때) 읽기 세션이 아직 닫히지 않았는지. 진짜 yield 의존성으로 확인한다."""
    monkeypatch.setattr(export, "CHUNK", 2)
    for i in range(5):
        add(session, world["a_company"], world["a_supplier"], f"S-{i}", "품목")
    session.commit()
    events = []

    def read_db():  # get_read_db 처럼 yield 하고 끝나면 닫힘을 기록한다
        try:
            yield session
        finally:
            events.append("closed")

    real = products_service.list_products
    monkeypatch.setattr(products_service, "list_products", lambda *a, **k: (events.append("fetch"), real(*a, **k))[1])
    login_as(client)
    app.dependency_overrides[get_read_db] = read_db
    rows = read_csv(client.get(URL, params={"format": "csv"}).content)
    assert len(rows) == 1 + 5
    assert events == ["fetch", "fetch", "fetch", "closed"]  # 3쪽을 다 읽은 뒤에야 세션이 닫힌다


def test_other_company_never_included(client, world, session):
    add(session, world["a_company"], world["a_supplier"], "MINE", "우리 품목")
    add(session, world["b_company"], world["b_supplier"], "THEIRS", "남의 품목")
    session.commit()
    login_as(client)
    for fmt in ("csv", "xlsx"):
        body = client.get(URL, params={"format": fmt}).content
        rows = read_csv(body) if fmt == "csv" else read_xlsx(body)
        assert [r[0] for r in rows[1:]] == ["MINE"]
        assert b"THEIRS" not in body and "B업체".encode() not in body


def test_formula_injection_neutralized(client, world, session):
    """위험한 글자로 시작하는 글자 칸은 CSV 는 ' 를 붙이고, xlsx 는 문자열 칸(수식 태그 없음). 숫자 칸은 숫자 그대로."""
    for i, bad in enumerate(INJECTIONS):
        add(session, world["a_company"], world["a_supplier"], f"INJ-{i}", bad, color=bad, unit_cost=1200)
    session.commit()
    login_as(client)

    rows = read_csv(client.get(URL, params={"format": "csv"}).content)
    names = {r[0]: (r[1], r[9], r[3]) for r in rows[1:]}  # SKU → (품목명, 색상, 구매단가)
    for i, bad in enumerate(INJECTIONS):
        assert names[f"INJ-{i}"] == ("'" + bad, "'" + bad, "1200")  # 숫자는 ' 없이 그대로

    body = client.get(URL, params={"format": "xlsx"}).content
    sheet_xml = zipfile.ZipFile(io.BytesIO(body)).read("xl/worksheets/sheet1.xml").decode()
    assert "<f>" not in sheet_xml and "<f " not in sheet_xml  # 수식 칸이 하나도 없다
    ws = load_workbook(io.BytesIO(body)).worksheets[0]
    by_sku = {row[0].value: row for row in ws.iter_rows(min_row=2)}
    for i, bad in enumerate(INJECTIONS):
        name, cost = by_sku[f"INJ-{i}"][1], by_sku[f"INJ-{i}"][3]
        assert (name.value, name.data_type) == (bad.replace("\r", "\n"), "s")  # 값은 그대로(xlsx XML 은 CR 을 줄바꿈으로 읽는다), 문자열 칸
        assert (cost.value, cost.data_type) == (1200, "n")  # 숫자 칸


def test_korean_special_chars_and_no_sensitive_columns(client, world, session):
    text = '쉼표,따옴표"줄바꿈\n이모지😀'
    add(session, world["a_company"], world["a_supplier"], "KO-1", text, spec="2L·500㎖")
    session.commit()
    login_as(client)
    for fmt in ("csv", "xlsx"):
        body = client.get(URL, params={"format": fmt}).content
        rows = read_csv(body) if fmt == "csv" else read_xlsx(body)
        assert list(rows[0]) == export.PRODUCT_HEADERS  # 허용한 열만 (번호·회사·시각·해시 없음)
        assert (rows[1][1], rows[1][11], rows[1][13]) == (text, "2L·500㎖", "A업체")
        assert b"@a.test" not in body and b"argon2" not in body  # 사용자 이메일·비밀번호 해시 없음


def test_headers_match_import_template():
    assert export.PRODUCT_HEADERS[:13] == TEMPLATE_HEADERS  # 같은 순서·이름이어야 다시 가져올 수 있다


@pytest.mark.parametrize("fmt", ["xlsx", "csv"])
def test_round_trip_into_import_preview(client, world, session, fmt):
    """내보낸 파일을 그대로 품목 가져오기 미리보기에 넣으면 문제 0·신규 0·수정 0 (변경 없음만)."""
    a, sup = world["a_company"], world["a_supplier"]
    other = Supplier(company_id=a.id, name="A2업체", lead_time_days=3)
    session.add(other)
    session.flush()
    add(session, a, sup, "RT-PLAIN", "발주단위 없음")  # 화면 응답은 발주단위 EA·1 로 채우지만 파일은 빈칸이어야 한다
    add(session, a, other, "RT-BOX", "박스 품목", unit="개", unit_cost=1000, safety_stock=5, order_unit="BOX",
        units_per_box=12, box_unit_cost=11000, min_order_units=2, color="검정", size="M", spec="2L", group_code="GRP-1")
    add(session, a, sup, "RT-INJ", "=1+1", color="-빨강", group_code="@G")
    add(session, a, sup, "RT-OFF", "비활성 품목", is_active=False)
    session.commit()
    login_as(client)

    body = client.get(URL, params={"format": fmt, "include_inactive": "true"}).content
    headers = [str(h) for h in (read_csv(body) if fmt == "csv" else read_xlsx(body))[0]]
    cols = {k: v for k, v in suggest_columns(headers, HINTS).items() if v is not None}
    preview = client.post("/api/v1/product-imports/preview", files={"file": (f"p.{fmt}", body)},
                          data={"options": json.dumps({**cols, "default_supplier_id": sup.id})})
    assert preview.status_code == 200, preview.text
    data = preview.json()["data"]
    assert (data["problem_count"], data["new_count"], data["update_count"], data["unchanged_count"]) == (0, 0, 0, 4)


def test_unquote_only_before_formula_chars():
    assert [_unquote(c) for c in ["'=1+1", "'-1", "'＝1", "'\t=1", "'A01", "''=x", "'", "it's", "=1"]] == [
        "=1+1", "-1", "＝1", "\t=1", "'A01", "''=x", "'", "it's", "=1"]


def test_too_large_bad_format_and_login(client, world, session, monkeypatch, caplog):
    monkeypatch.setattr(export, "MAX_ROWS", 2)
    for i in range(3):
        add(session, world["a_company"], world["a_supplier"], f"BIG-{i}", "품목")
    session.commit()
    assert client.get(URL, params={"format": "csv"}).status_code == 401  # 로그인 없음
    login_as(client)
    with caplog.at_level(logging.INFO, logger="app.services.export"):
        too_large = client.get(URL, params={"format": "xlsx"})
    assert too_large.status_code == 422 and too_large.json()["error"]["code"] == "EXPORT_TOO_LARGE"
    assert "rows=3 outcome=TOO_LARGE" in caplog.text
    assert client.get(URL, params={"format": "pdf"}).status_code == 422  # 잘못된 형식
    assert client.get(URL).status_code == 422  # 형식 없음


def test_both_roles_and_log_line(client, world, session, caplog):
    """관리자·담당자 둘 다 내보낼 수 있다(사용자 결정). 로그는 한 줄: 누가·무엇·몇 행, 파일 내용·검색어는 없다."""
    add(session, world["a_company"], world["a_supplier"], "LOG-1", "비밀스러운 품목명")
    session.commit()
    for email in ("admin@a.test", "staff@a.test"):
        login_as(client, email)
        with caplog.at_level(logging.INFO, logger="app.services.export"):
            caplog.clear()
            response = client.get(URL, params={"format": "csv", "q": "비밀"})
        assert response.status_code == 200 and response.headers["content-disposition"].startswith('attachment; filename="products-')
        records = [r.getMessage() for r in caplog.records if r.name == "app.services.export"]
        assert len(records) == 1 and "target=products fmt=csv" in records[0] and "rows=1 outcome=OK" in records[0]
        assert "비밀" not in records[0] and "@a.test" not in records[0]
