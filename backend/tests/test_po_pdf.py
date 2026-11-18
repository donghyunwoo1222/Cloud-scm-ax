"""발주서 서버 PDF(#264 PR2): 쪽 넘김, 표 머리 반복, 도장 좌표·크기, 승인 기록. DB 없이 문서 dict 만 쓴다."""

import re  # 그려진 사각형 읽기

import pytest  # 테스트 도구
from fpdf import FPDF  # 그리기 호출을 가로채 기록한다
from fpdf.recorder import FPDFRecorder  # unbreakable 이 되감을 때 기록도 되감는다

from app.services import po_document as pd  # 대상 모듈


def make_doc(count=1, buyer="한빛생활용품", company=None, approver="박관리", at="2026-11-18 09:30", supplier=None):
    """build_document 결과와 같은 모양의 문서 dict. company = 승인 시점 상호(없으면 buyer 와 같음)."""
    lines = [{"no": i + 1, "product_name": f"품목 {i + 1}", "product_sku": f"SKU-{i + 1:03d}", "unit": "개",
              "quantity": 10, "unit_price": 1000, "amount": 10000, "note": ""} for i in range(count)]
    supply = 10000 * count
    name = company or buyer
    return {
        "po_number": "PO-20261118-001", "status": "APPROVED", "order_date": "2026-11-18",
        "supplier": {"name": "대한물산", "contact_name": "김대한", "phone": "02-111-2222", "email": "a@b.kr"} | (supplier or {}),
        "buyer": {"name": buyer, "business_number": "1234567890", "representative": "홍길동", "phone": "031-000-1111",
                  "address": "경기도 성남시 1-2", "author_name": "이수진"},
        "lines": lines, "supply_total": supply, "vat": supply // 10, "total": supply + supply // 10, "total_korean": "만",
        "due_date": "2026-11-30", "delivery_address": "경기도 성남시 1-2", "payment_terms": "월말", "memo": "포장 주의",
        "approval": {"approver_name": approver, "approved_at": at, "company_name": name, "stamp": pd.stamp_of(name)},
    }


@pytest.fixture
def calls(monkeypatch):
    """그리는 호출 기록: (pdf id, 쪽, x, y, 글자, 종류). unbreakable 이 되감으면 그 사이 기록도 지운다."""
    log = []
    for kind in ("cell", "multi_cell", "text"):
        original = getattr(FPDF, kind)

        def wrap(self, *args, _original=original, _kind=kind, **kwargs):
            if not kwargs.get("dry_run"):
                words = [a for a in args if isinstance(a, str)] + [v for k, v in kwargs.items() if k in ("text", "txt") and isinstance(v, str)]
                x, y = (args[0], args[1]) if _kind == "text" else (self.x, self.y)  # text() 는 인자가 좌표(기준선), 칸은 현재 위치
                log.append((id(self), self.page, x, y, words[-1] if words else "", _kind, args))
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(FPDF, kind, wrap)
    init, rewind = FPDFRecorder.__init__, FPDFRecorder.rewind

    def new_init(self, *args, **kwargs):
        init(self, *args, **kwargs)
        self._mark = len(log)  # 이 시점까지가 확정된 기록

    def new_rewind(self):
        del log[self._mark:]  # 되감으면 시험 삼아 그린 기록은 버린다 (곧 다시 그려진다)
        rewind(self)

    monkeypatch.setattr(FPDFRecorder, "__init__", new_init)
    monkeypatch.setattr(FPDFRecorder, "rewind", new_rewind)
    return log


def render(doc, calls):
    """PDF 를 만들고, 그 PDF 에 그려진 (쪽, 글자) 목록과 (쪽, 글자, x, y) 위치를 돌려준다."""
    calls.clear()
    pdf = pd.render_pdf(doc)
    mine = [c for c in calls if c[0] == id(pdf)]
    return pdf, mine


def pages_of(mine, needle):
    return {c[1] for c in mine if needle in c[4]}


def test_page_count_and_repeated_heading(calls):
    pdf, mine = render(make_doc(1), calls)
    assert pdf.pages_count == 1
    pdf, mine = render(make_doc(40), calls)
    assert pdf.pages_count >= 2
    assert {1, 2} <= pages_of(mine, "품목명")  # 2쪽에도 표 머리


def test_page_has_room_for_at_least_14_items(calls):
    pdf, _ = render(make_doc(14), calls)
    assert pdf.pages_count == 1


@pytest.mark.parametrize("count", range(1, 41))
def test_closing_block_never_splits(calls, count):
    _, mine = render(make_doc(count), calls)
    pages = {pages_of(mine, key).pop() for key in ("1) 납기일자", "4) 기타", "위와 같이 발주합니다.", "승인 :")}
    assert len(pages) == 1, (count, pages)


def test_min_five_rows_are_padded(calls):
    _, one = render(make_doc(1), calls)
    _, five = render(make_doc(5), calls)
    count = lambda mine: len([c for c in mine if c[5] == "multi_cell" and c[4] == ""])
    assert count(one) - count(five) == 0 or count(one) >= 4 * 7  # 빈 줄 4개 × 7칸이 더 그려진다
    assert count(one) >= count(five)


NAMES = ["가", "한빛", "한빛상사", "한빛생활용품", "한빛생활용품유통", "한빛생활용품유통 주식회사 경기지점",
         "A&B<주>", "Hanbit Living Co", "(주)한빛생활", "주식회사"]


@pytest.mark.parametrize("name", NAMES)
def test_stamp_text_is_drawn_and_fits_inner_circle(calls, name):
    doc = make_doc(2, buyer=name)
    pdf, mine = render(doc, calls)
    stamp = doc["approval"]["stamp"]
    drawn = [c for c in mine if c[5] == "text"]
    assert [c[4] for c in drawn] == stamp["lines"]  # 줄마다 text() 로 그려졌다
    d = pd.PDF_STAMP_D
    f = stamp["ratio"] * d
    pdf.set_font("Nanum", "B", f / 0.3528)
    cx, cy = pd.PDF_TABLE_RIGHT - 0.5 - d / 2, drawn[0][3] - 0.37 * f + (len(drawn) - 1) / 2 * 1.1 * f  # 그려진 위치에서 거꾸로 구한 중심
    for call in drawn:
        width = pdf.get_string_width(call[4])
        assert abs(call[2] - (cx - width / 2)) < 1e-6  # 가로 가운데 맞춤
        corner = ((width / 2) ** 2 + (abs(call[3] - 0.37 * f - cy) + f / 2) ** 2) ** 0.5
        assert corner <= 41 * d / 100, (name, call[4], corner)  # 안쪽 원(41u) 안


def test_stamp_rows_match_screen_formula():
    rows = pd.stamp_pdf_rows({"lines": ["한빛", "생활", "가게"], "ratio": 0.2}, 100, 50, 19)
    f = 0.2 * 19
    assert rows["font_mm"] == pytest.approx(f)
    assert rows["font_pt"] == pytest.approx(f / 0.3528)
    for i, row in enumerate(rows["rows"]):
        assert row["y"] == pytest.approx(50 + (i - 1) * 1.1 * f)  # 화면 stampRows: 50 + (i − (n−1)/2) × 1.1 f
        assert row["baseline"] == pytest.approx(row["y"] + 0.37 * f)


LONG_SUP = "대한물산유통서비스 주식회사 경기남부지점 영업본부"
LONG_BUY = "한빛생활용품유통 주식회사 경기지점 본사 영업 1팀 별관"


@pytest.mark.parametrize(("buyer", "supplier"), [
    ("한빛", {}), (LONG_BUY, {}),  # 기존: 발주처만 길 때
    ("한빛", {"name": LONG_SUP}),  # 수신처 상호만 길다
    (LONG_BUY, {"name": LONG_SUP}),  # 둘 다 길다
    ("한빛", {"contact_name": "김" * 40}),  # 수신처 담당자가 길다 (상호 아래 행)
    ("한빛", {"email": "very.long.email.address.for.the.supplier@example-company-name.co.kr"}),  # 수신처 이메일이 길다
    ("한빛", {"phone": "02-111-2222 / 031-333-4444 / 010-5555-6666 / 팩스 02-777-8888"}),  # 수신처 연락처가 길다
])
def test_stamp_center_follows_name_row(calls, buyer, supplier):
    """도장 세로 중심 = 그려진 발주처 상호 칸(행 높이는 수신처·발주처 칸 중 큰 쪽)의 가운데 − 0.08d. 칸 위치는 PDF 에 그려진 사각형에서 읽는다."""
    doc = make_doc(1, buyer=buyer, supplier=supplier)
    pdf, mine = render(doc, calls)
    k = 72 / 25.4  # mm → pt
    rects = re.findall(r"([\d.]+) ([\d.]+) ([\d.]+) ([\d.]+) re S", bytes(pdf.pages[1].contents).decode("latin-1"))
    _x, y, _w, h = next(tuple(float(v) for v in r) for r in rects if abs(float(r[2]) - 62 * k) < 0.1)  # 폭 62mm: 발주처 상호 칸
    top, height = (297 * k - y - h) / k, h / k
    f = doc["approval"]["stamp"]["ratio"] * pd.PDF_STAMP_D
    drawn = [c for c in mine if c[5] == "text"]
    cy = drawn[0][3] - 0.37 * f + (len(drawn) - 1) / 2 * 1.1 * f  # 그려진 기준선에서 거꾸로 구한 도장 중심
    assert cy == pytest.approx(top + height / 2 - 0.08 * pd.PDF_STAMP_D, abs=0.02)
    if buyer == "한빛" and not supplier:
        assert height == pytest.approx(8.75, abs=0.02)  # 한 줄이면 발주번호 칸(35mm)을 네 행이 나눠 8.75mm


def test_approval_lines(calls):
    _, empty = render(make_doc(1, approver=None, at=None), calls)
    assert any(c[4] == "승인 : - · - (전자 승인 표시)" for c in empty)
    _, same = render(make_doc(1), calls)
    assert any(c[4].startswith("승인 : 박관리 · 2026-11-18 09:30") for c in same)
    assert not any("승인 시점 상호" in c[4] for c in same)  # 상호가 같으면 줄 없음
    _, renamed = render(make_doc(1, buyer="새상호", company="옛상호"), calls)
    assert any(c[4] == "(승인 시점 상호 : 옛상호)" for c in renamed)


def test_build_pdf_has_no_metadata():
    data = pd.build_pdf(make_doc(1))
    assert data.startswith(b"%PDF")
    assert b"/Author" not in data and b"/Title" not in data
