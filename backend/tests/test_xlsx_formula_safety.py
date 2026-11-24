"""엑셀 수식 주입 방지 (#280): 사용자 입력 글자가 "="로 시작해도 발주서 엑셀에서 수식이 아니라 글자로 저장된다. DB 없이 순수 함수만 검사한다."""

from io import BytesIO  # 만든 엑셀을 메모리에서 다시 연다

import pytest  # 테스트 도구
from openpyxl import Workbook, load_workbook  # 엑셀 쓰기·읽기

from app.services.export import csv_text, xlsx_cell  # 글자 고정 함수 (목록 내보내기와 같은 것)
from app.services.po_document import build_xlsx  # 발주서 엑셀

# 입력 예: 수식, 링크 수식, 앞 공백 수식, 일반 글자, 빈 글자
TEXTS = ["=1+1", '=HYPERLINK("http://x","y")', "  =1+1", "일반 글자", ""]


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@a", "\t=1", "＝1"])
def test_csv_text_prefixes_quote(value):
    assert csv_text(value) == "'" + value  # 위험한 글자로 시작하면 앞에 ' 를 붙인다


@pytest.mark.parametrize("value", ["  =1+1", "", "일반 글자", 5, -5, None])
def test_csv_text_leaves_others(value):
    assert csv_text(value) == value  # 앞 공백·빈 글자·일반 글자·숫자는 그대로 (앞 공백은 엑셀이 수식으로 읽지 않는다고 보고 막지 않음)


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@a", "  =1+1", "일반 글자"])
def test_xlsx_cell_is_text(value):
    wb = Workbook()
    ws = wb.active
    ws.append([xlsx_cell(ws, value)])
    cell = load_workbook(_save(wb)).active["A1"]
    assert cell.data_type == "s" and cell.value == value  # 저장 후 다시 열어도 글자, 값 그대로 (빈 글자는 엑셀이 칸을 비워 저장하므로 제외)


def test_xlsx_cell_keeps_numbers_and_none():
    assert xlsx_cell(None, 5) == 5 and xlsx_cell(None, None) is None  # 숫자·빈칸은 그대로 (합계가 나와야 함)


def _save(wb):
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def make_doc(text):
    """사용자 입력 유래 칸을 모두 text 로 채운 발주서 문서 (build_document 응답과 같은 모양)."""
    return {
        "po_number": "PO-1", "order_date": "2026-11-17", "status": "ORDERED",
        "supplier": {"name": text, "contact_name": text, "phone": text, "email": text},
        "buyer": {"name": text, "business_number": text, "representative": text, "phone": text, "address": text, "author_name": text},
        "lines": [{"no": 1, "product_name": text, "product_sku": "S1", "unit": text, "quantity": 10, "unit_price": 1000, "amount": 10000, "note": text}],
        "currency": "KRW", "freight_terms": None, "special_terms": None,  # #267 PR3 새 공개 칸
        "supply_total": 10000, "vat": 1000, "total": 11000, "total_korean": "일만일천",
        "due_date": "2026-11-30", "delivery_address": text, "payment_terms": text, "memo": text,
        "approval": {"approver_name": text, "approved_at": "2026-11-17 09:00", "company_name": "회사", "stamp": {}},
    }


@pytest.mark.parametrize("text", TEXTS)
def test_build_xlsx_user_text_cells_are_text(text):
    ws = load_workbook(BytesIO(build_xlsx(make_doc(text)))).active
    checked = 0
    for row in ws.iter_rows():
        for cell in row:
            if cell.value is not None and isinstance(cell.value, str) and text and text in cell.value:
                assert cell.data_type == "s", (cell.coordinate, cell.value)  # 수식(f)으로 저장되면 안 된다
                checked += 1
            assert cell.data_type != "f", cell.coordinate  # 어느 칸도 수식이 아니다
    if text:
        # 수신처 4 + 발주처 5(사업자번호는 글자가 바뀌어 찾기에서 제외) + 품목 3 + 조건 3 + 승인 1 = 16칸
        assert checked == 16, checked


def test_build_xlsx_number_cells_stay_numbers():
    ws = load_workbook(BytesIO(build_xlsx(make_doc("=1+1")))).active
    item_row = next(r for r in ws.iter_rows() if r[0].value == 1)  # 품목 줄
    assert [c.data_type for c in item_row[3:6]] == ["n", "n", "n"]  # 수량·단가·금액은 숫자
    assert [c.value for c in item_row[3:6]] == [10, 1000, 10000]
    totals = {r[4].value: r[5] for r in ws.iter_rows() if r[4].value in ("공급가액 합계", "부가세 (10%)", "합계")}
    assert all(c.data_type == "n" for c in totals.values())  # 합계·세금도 숫자
