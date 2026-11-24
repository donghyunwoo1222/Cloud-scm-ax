"""발주서 문서(#157): 인쇄 화면과 엑셀이 같이 쓰는 값을 서버에서 한 번만 계산한다. 화면·엑셀 숫자가 어긋나지 않게 하려는 것."""

import math  # 도장 글자 크기 계산 (제곱근·내림)
from decimal import Decimal  # 외화 금액 (float 로 바꾸지 않는다)
from io import BytesIO  # 엑셀을 메모리에서 만든다 (디스크 저장 없음)
from pathlib import Path  # 폰트 파일 위치

from fpdf import FPDF  # PDF 만들기 (메일 첨부, #158)
from fpdf.enums import MethodReturnValue  # multi_cell 이 높이만 돌려주게 (도장 위치 계산)
from fpdf.fonts import FontFace  # 표 머리 칸 글씨 모양
from openpyxl import Workbook  # .xlsx 쓰기 (#154에서 설치한 라이브러리)
from openpyxl.styles import Alignment, Font  # 가운데 정렬·굵은 글씨
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL  # 서울 시간대 (발주일자)
from app.config import settings  # FX_ENABLED 스위치
from app.errors import AppError  # 공통 오류
from app.models import Company, Supplier, User  # 표들
from app.services import purchase_orders as po_service  # 발주서 조회·응답 만들기
from app.services.export import (  # 서울 시각 글자, 사용자 id → 이름, 글자 고정 칸
    seoul_time,
    user_names,
    xlsx_cell,
)
from app.services.po_money import CURRENCIES  # 통화별 소수 자릿수
from app.services.po_states import ACTION_STATES  # 문서를 만들 수 있는 상태 (#260)
from app.services.tenant import get_owned  # 회사 조건이 붙은 조회

DIGITS = "영일이삼사오육칠팔구"  # 숫자 → 한글
SMALL_UNITS = ("", "십", "백", "천")  # 네 자리 묶음 안의 자릿수
BIG_UNITS = ("", "만", "억", "조", "경")  # 네 자리 묶음 이름
STAMP_DROP = ("주식회사", "(주)", "㈜")  # 도장에서 떼는 회사 형태 표기
STAMP_RADIUS = 37  # 글자 묶음 모서리가 들어갈 반지름 (도장 지름 100 기준, 안쪽 원 41보다 약간 작게)
PDF_STAMP_D = 19  # PDF 도장 지름 (mm). 화면 도장 72px(약 19mm)과 같은 크기
PDF_STAMP_RED = (198, 40, 40)  # 도장 색 #c62828 (화면과 같음)
PDF_TABLE_RIGHT = 195  # 표 오른쪽 끝 (mm): 왼쪽 여백 15 + 본문 폭 180
PDF_MIN_ROWS = 5  # 품목 표 최소 줄 수 (화면 MIN_ROWS 와 같게)
FREIGHT_LABELS = {  # 운송비 조건 코드 → 공급업체 문서에 쓰는 글자 (금액은 내부 전용이라 조건만 나간다)
    "INCLUDED": "단가에 포함", "BILLED": "운임 청구", "COLLECT": "착불", "EXW": "EXW", "FOB": "FOB", "CIF": "CIF", "DDP": "DDP",
}
FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"  # 한글 폰트(나눔고딕, OFL). 도커 이미지에 한글 폰트가 없어 저장소에 넣었다


def vat_of(supply_total: int) -> int:
    """부가세 = 공급가액 합계의 10%, 원 미만 버림 (줄별 세액 없음). 예) 1,005 → 100."""
    return supply_total // 10


def fx_fmt(value: str, currency: str) -> str:
    """외화 금액 글자("1000" → "1,000.00") 를 통화 자릿수로 (USD·EUR·CNY 2자리, JPY·VND 0자리)."""
    return f"{Decimal(value):,.{CURRENCIES[currency][1]}f}"


def money_text(doc: dict, value, code: bool = False) -> str:
    """문서 금액 글자. 원화는 천 단위 쉼표, 외화는 통화 자릿수(code=True 면 "USD 1,000.00")."""
    if doc["currency"] == "KRW":
        return f"{value:,}"
    return f"{doc['currency']} {fx_fmt(value, doc['currency'])}" if code else fx_fmt(value, doc["currency"])


def condition_rows(doc: dict) -> list[tuple[str, str | None]]:
    """발주 조건 줄 (라벨, 값). 운송조건·특약은 값이 있을 때만 붙어, 없으면 기존 원화 출력과 같다. 엑셀·PDF·메일·화면이 같은 목록을 쓴다."""
    rows = [("납기일자", doc["due_date"]), ("납품장소", doc["delivery_address"]), ("지불조건", doc["payment_terms"]), ("기타", doc["memo"])]
    rows += [(label, doc[key]) for label, key in (("운송조건", "freight_terms"), ("특약", "special_terms")) if doc[key]]
    return rows


def korean_amount(n: int) -> str:
    """금액을 한글로: 836000 → '팔십삼만육천'. 0 은 '영'. 금액 문서 관례대로 1 도 읽는다('일십만', '일천').

    shortcut: 경(10^16) 이상 묶음까지만 이름이 있다(10^20 미만). 수량·단가 상한으로 충분하며, 넘으면 ValueError.
    """
    if n < 0 or n >= 10**20:
        raise ValueError("지원하지 않는 금액입니다.")
    if n == 0:
        return DIGITS[0]
    groups = []  # 네 자리씩 끊은 값 (작은 쪽부터)
    while n:
        groups.append(n % 10000)
        n //= 10000
    parts = []
    for index in range(len(groups) - 1, -1, -1):  # 큰 묶음부터
        group = groups[index]
        if group == 0:  # 0000 묶음은 건너뛴다 (예: 1억 → 일억)
            continue
        text = ""
        for place in range(3, -1, -1):  # 천·백·십·일 자리
            digit = group // 10**place % 10
            if digit:
                text += DIGITS[digit] + SMALL_UNITS[place]
        parts.append(text + BIG_UNITS[index])
    return "".join(parts)


def fmt_business_number(number: str | None) -> str | None:
    """숫자 10자리 → 123-45-67890 (비어 있으면 그대로 비움)."""
    return f"{number[:3]}-{number[3:5]}-{number[5:]}" if number else number


def stamp_of(name: str) -> dict:
    """회사명 → 원형 도장 글자 배치 (#263). 화면·PDF·메일이 모두 이 결과만 그린다(규칙은 여기 한 곳).

    lines: 줄별 글자 (앞줄이 길거나 같게), ratio: 글자 크기 ÷ 도장 지름. 이스케이프는 그리는 쪽이 한다.
    ratio 는 "가장 긴 줄의 폭"이 아니라 글자 묶음의 모서리 거리로 맞춘다. 원은 위아래로 갈수록 가로 폭이 좁아져,
    줄이 많으면 윗줄·아랫줄 모서리가 원을 뚫기 때문이다. 화면(글자 크기 = ratio×100, 줄 간격 ×1.1, 중앙 정렬)과 짝이다.
    예) "(주)한빛생활" → {"lines": ["한빛", "생활"], "ratio": 0.255}, 지름 64px 이면 글자 16.3px.
    """
    compact = "".join(name.split())  # 앞뒤·안쪽 공백 모두 제거
    text = compact
    for word in STAMP_DROP:
        text = text.replace(word, "")
    text = (text or compact or "인")[:9]  # 형태 표기만 있던 이름은 원래 이름, 그것도 비면 "인". 10자 이상은 앞 9자
    rows = 1 if len(text) <= 3 else 2 if len(text) <= 6 else 3  # 1~3자 1줄, 4~6자 2줄, 7~9자 3줄
    base, extra = divmod(len(text), rows)  # 남는 글자는 앞줄부터 한 자씩 (7자 → 3/2/2)
    lines, start = [], 0
    for row in range(rows):
        size = base + (row < extra)
        lines.append(text[start:start + size])
        start += size
    # 글자 묶음의 모서리가 R=37(안쪽 원 41보다 약간 작게) 안에 들어오는 최대 크기. 가장 긴 줄은 첫 줄
    half_width = len(lines[0]) / 2  # 글자 크기 f 의 절반 폭 단위: 폭 = 글자 수 × f
    half_height = ((rows - 1) * 1.1 + 1) / 2  # 줄 간격 1.1f, 한 줄 높이 f → 묶음 높이 = ((줄 수−1)×1.1+1)×f
    ratio = min(0.36, (STAMP_RADIUS / 100) / math.sqrt(half_width**2 + half_height**2))  # 모서리 거리 = f×√(..)
    ratio = math.floor(ratio * 1000) / 1000  # 소수 셋째 자리 내림 (반올림하면 살짝 넘을 수 있다). 1~2자는 0.36 상한
    return {"lines": lines, "ratio": round(ratio, 3)}


def build_document(company_id: int, db: Session, order_id: int) -> dict:
    """GET /purchase-orders/{id}/document 응답. 다른 회사·없는 id 는 404, 승인 전·취소는 409. 회사 정보가 비어도 만들어진다."""
    order = po_service.get_order(company_id, db, order_id)  # 다른 회사 404
    if order.status not in ACTION_STATES["document"]:  # 승인 이후만 (DRAFT·CANCELLED 는 409)
        raise AppError(409, "INVALID_STATUS", "승인된 발주서만 문서로 볼 수 있습니다.", {"status": order.status})
    if order.currency != "KRW" and not settings.fx_enabled:  # 외화 문서는 FX_ENABLED 가 켜질 때만 (국내 먼저 배포, #267)
        raise AppError(409, "FX_DOCUMENT_NOT_READY", "외화 발주서의 문서·메일은 아직 준비 중입니다.", {"currency": order.currency})
    out = po_service.build_out(company_id, db, [order])[0]  # 줄 금액은 발주서 응답과 같은 계산을 쓴다
    company = db.get_one(Company, company_id)
    supplier = get_owned(company_id, db, Supplier, order.supplier_id)
    author = get_owned(company_id, db, User, order.created_by)  # 작성자 (같은 회사 사용자)
    stamp_name = order.approved_company_name or company.name  # 승인 시점 회사명. 승인 칸 없이 만든 발주서는 현재 회사명
    currency = order.currency
    fx = currency != "KRW"  # 외화: 줄에는 외화만(환산 원화는 내부 전용), 부가세·한글 금액 없음 (#268 보류)
    digits = Decimal(1).scaleb(-CURRENCIES[currency][1])  # 통화 자릿수 (USD 0.01, JPY 1)
    fx_str = lambda v: str(Decimal(v).quantize(digits))  # 외화는 글자로 넘긴다 (JSON 이 float 로 바꿔 자릿수가 깨지지 않게)
    lines = []
    for number, item in enumerate(out["items"], start=1):
        boxed = item["box_quantity"] is not None  # 박스 발주는 박스 단위로 적는다
        price = item["fx_box_unit_price"] if boxed else item["fx_unit_price"] if fx else None
        lines.append({
            "no": number,
            "product_name": item["product_name"], "product_sku": item["product_sku"],
            "unit": item["order_unit"] if boxed else item["unit"],  # 발주 당시 발주단위 이름 (예: 박스, PACK)
            "quantity": item["box_quantity"] if boxed else item["quantity"],
            "unit_price": fx_str(price) if fx else item["box_unit_price"] if boxed else item["unit_price"],
            "amount": fx_str(item["fx_line_total"]) if fx else item["line_total"],
            "note": f"1{item['order_unit']}={item['units_per_box']:,}{item['unit']}" if boxed else "",  # 예: 1박스=10개
        })
    if fx:
        supply_total = fx_str(sum(Decimal(line["amount"]) for line in lines))
        vat, total, total_korean = None, supply_total, None
    else:
        supply_total = sum(line["amount"] for line in lines)
        vat = vat_of(supply_total)
        total, total_korean = supply_total + vat, korean_amount(supply_total + vat)
    return {
        "po_number": order.po_number,
        "status": order.status,
        "order_date": order.created_at.astimezone(SEOUL).date().isoformat(),  # 발주일자 = 작성일 (서울 기준)
        "supplier": {"name": supplier.name, "contact_name": supplier.contact_name, "phone": supplier.phone, "email": supplier.email},
        "buyer": {
            "name": company.name, "business_number": company.business_number, "representative": company.representative,
            "phone": company.phone, "address": company.address, "author_name": author.name,
        },
        "lines": lines,
        "currency": currency,  # 공개: 통화 코드
        "supply_total": supply_total, "vat": vat, "total": total, "total_korean": total_korean,
        "due_date": order.due_date.isoformat() if order.due_date else None,
        "delivery_address": order.delivery_address or company.address,  # 비면 회사 주소
        "payment_terms": order.payment_terms,
        "memo": order.memo,
        "freight_terms": FREIGHT_LABELS.get(order.freight_terms),  # 공개: 운송비 조건 (금액·환율·원화 환산·부대비용·원가는 문서에 넣지 않는다)
        "special_terms": order.special_terms,  # 공개: 공급업체와 합의하는 특약
        "approval": {  # 승인 기록과 도장 (#263). 승인 칸이 빈 발주서는 이름·시각이 null
            "approver_name": user_names(company_id, db, {order.approved_by}).get(order.approved_by),
            "approved_at": seoul_time(order.approved_at),  # 서울 "YYYY-MM-DD HH:MM"
            "company_name": stamp_name,
            "stamp": stamp_of(stamp_name),
        },
    }


def build_xlsx(doc: dict) -> bytes:
    """문서 응답과 같은 값으로 엑셀 한 장을 만든다. 숫자는 숫자 칸으로 넣어 합계 계산에 쓸 수 있다."""
    wb = Workbook()
    wb.properties.creator = ""  # 파일 속성 작성자 기본값 "openpyxl" 을 비운다 (PDF 속성이 빈 것과 같은 정책, #281)
    ws = wb.active
    ws.title = doc["po_number"]
    bold = Font(bold=True)
    txt = lambda value: xlsx_cell(ws, value)  # 사용자 입력 유래 글자 칸: "="로 시작하는 글자가 수식이 되지 않게 글자로 고정 (#280)
    ws.append(["발 주 서"])
    ws["A1"].font = Font(bold=True, size=16)
    ws.append(["발주번호", doc["po_number"], "발주일자", doc["order_date"]])
    s, b = doc["supplier"], doc["buyer"]
    ws.append(["[수신처]"])
    ws.append(["상호", txt(s["name"]), "담당자", txt(s["contact_name"]), "연락처", txt(s["phone"]), "이메일", txt(s["email"])])
    ws.append(["[발주처]"])
    ws.append(["상호", txt(b["name"]), "사업자번호", txt(fmt_business_number(b["business_number"])), "대표자", txt(b["representative"])])
    ws.append(["연락처", txt(b["phone"]), "주소", txt(b["address"]), "담당자(작성자)", txt(b["author_name"])])
    ws.append([])
    fx = doc["currency"] != "KRW"
    ws.append([f"합계금액: {money_text(doc, doc['total'], True)} (부가세 제외)" if fx
               else f"합계금액: 일금 {doc['total_korean']} 원정 (₩{doc['total']:,}, 부가세 포함)"])
    header_row = ws.max_row + 1
    cur = f" ({doc['currency']})" if fx else ""  # 외화 표는 열 머리에 통화를 적는다
    ws.append(["No.", "품목명 (SKU)", "단위", "수량", f"단가{cur}", f"공급가액{cur}", "비고"])
    for cell in ws[header_row]:
        cell.font = bold
        cell.alignment = Alignment(horizontal="center")
    for line in doc["lines"]:
        num = Decimal if fx else int  # 외화는 Decimal 로 넣어 숫자 칸이 되게 (float 오차 없음)
        ws.append([line["no"], txt(f"{line['product_name']} ({line['product_sku']})"), txt(line["unit"]), line["quantity"],
                   num(line["unit_price"]), num(line["amount"]), txt(line["note"])])
    totals = ((("합계 (부가세 제외)", Decimal(doc["total"])),) if fx else
              (("공급가액 합계", doc["supply_total"]), ("부가세 (10%)", doc["vat"]), ("합계", doc["total"])))
    for label, value in totals:
        ws.append([None, None, None, None, label, value])
        ws.cell(ws.max_row, 5).font = bold
    decimals = CURRENCIES[doc["currency"]][1] if fx else 0
    price_format = "#,##0" + (f".{'0' * decimals}" if decimals else "")
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):  # 수량·단가·금액 칸은 천 단위 쉼표 (외화는 통화 자릿수)
        row[3].number_format = "#,##0"
        for cell in row[4:6]:
            cell.number_format = price_format
    ws.append([])
    ws.append(["발주 조건"])
    for number, (label, value) in enumerate(condition_rows(doc), start=1):  # 운송조건·특약은 값이 있을 때만
        ws.append([f"{number}) {label}", doc["due_date"] if label == "납기일자" else txt(value)])
    ap = doc["approval"]  # 승인 줄은 맨 끝에 붙여, 위쪽 줄의 위치·병합이 밀리지 않게 한다 (#263)
    ws.append([])
    ws.append(["승인", txt(f"{ap['approver_name'] or '-'} (인)"), "승인 시각", txt(ap["approved_at"] or "-")])  # 승인 칸이 빈 발주서는 "- (인)", "-". 이름이 "="로 시작해도 글자로 저장
    for col in (1, 3):
        ws.cell(ws.max_row, col).font = bold  # 라벨 칸은 굵게
    for column, width in zip("ABCDEFGH", (14, 28, 10, 12, 16, 16, 20, 24), strict=True):
        ws.column_dimensions[column].width = width
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def stamp_pdf_rows(stamp: dict, cx: float, cy: float, d: float) -> dict:
    """도장 글자 배치를 mm 좌표로 (PDF 객체 없이 계산, 화면 stampRows 와 같은 식). cx·cy = 도장 중심, d = 지름.

    줄 중심 y_i = cy + (i − (n−1)/2) × 1.1 × f, 기준선 = y_i + 0.37 × f. 가로 위치는 글자 폭이 필요해 그리는 쪽이 정한다.
    예) 2줄, d=19, ratio 0.255 → f=4.845mm, 줄 간격 5.33mm, 윗줄 중심 cy−2.66, 아랫줄 cy+2.66.
    """
    font_mm = stamp["ratio"] * d  # 글자 크기 f(mm)
    count = len(stamp["lines"])
    rows = []
    for i, text in enumerate(stamp["lines"]):
        y = cy + (i - (count - 1) / 2) * 1.1 * font_mm  # 줄 중심 (묶음 전체가 원 세로 중앙)
        rows.append({"text": text, "y": y, "baseline": y + 0.37 * font_mm})
    return {"font_mm": font_mm, "font_pt": font_mm / 0.3528, "rows": rows}


def draw_stamp(pdf: FPDF, stamp: dict, cx: float, cy: float, d: float = PDF_STAMP_D) -> None:
    """원 2개 + 글자를 벡터로 그린다 (화면 StampSeal 과 같은 비율). 밑의 글자가 비치게 곱하기 혼합 + 투명도 0.85."""
    unit = d / 100  # 지름 100 단위 → mm
    layout = stamp_pdf_rows(stamp, cx, cy, d)
    with pdf.local_context(fill_opacity=0.85, stroke_opacity=0.85, blend_mode="Multiply"):
        pdf.set_draw_color(*PDF_STAMP_RED)
        pdf.set_text_color(*PDF_STAMP_RED)
        pdf.set_line_width(4 * unit)
        pdf.circle(cx, cy, 46 * unit, style="D")  # 바깥 굵은 원
        pdf.set_line_width(1 * unit)
        pdf.circle(cx, cy, 41 * unit, style="D")  # 안쪽 가는 원
        pdf.set_font("Nanum", "B", layout["font_pt"])
        for row in layout["rows"]:
            pdf.text(cx - pdf.get_string_width(row["text"]) / 2, row["baseline"], row["text"])  # 가운데 맞춤


def render_pdf(doc: dict) -> FPDF:
    """문서 응답과 같은 값으로 A4 PDF(FPDF 객체)를 만든다. 여러 쪽이면 표 머리가 반복되고, 발주 조건~승인 줄은 쪽 경계에서 갈리지 않는다."""
    pdf = FPDF(format="A4")  # 단위 mm, 폭 210
    pdf.set_margins(15, 15)  # 좌우 15mm → 본문 폭 180mm
    pdf.add_font("Nanum", "", FONT_DIR / "NanumGothic-Regular.ttf")  # 보통 글씨
    pdf.add_font("Nanum", "B", FONT_DIR / "NanumGothic-Bold.ttf")  # 굵은 글씨
    pdf.add_page()
    pdf.set_font("Nanum", "B", 20)
    pdf.cell(0, 14, "발 주 서", align="C", new_x="LMARGIN", new_y="NEXT")  # 제목
    pdf.set_font("Nanum", "", 9.5)
    head = FontFace(emphasis="BOLD", fill_color=(238, 245, 228))  # 머리 칸: 굵게 + 화면(.po-paper th)과 같은 옅은 초록 #eef5e4
    s, b = doc["supplier"], doc["buyer"]
    blank = lambda v: v or ""
    table_top = pdf.get_y()  # 수신처 표의 윗선 (도장 위치 계산용)
    # 상호 칸의 위치·높이 (도장을 가운데에 찍으려고). 값 칸이 길어 접히면 그 줄 수만큼 행이 높아지고(수신처 칸 폭 46, 발주처 칸 폭 62),
    # 발주번호 칸(4행 합침)이 네 행 합보다 높으면 fpdf2 가 모자란 만큼을 네 행에 똑같이 나눠 더한다 (table.py 의 row_span_padding).
    fold = lambda width, text: pdf.multi_cell(width, 7, blank(text), dry_run=True, output=MethodReturnValue.HEIGHT)
    natural = [7, max(7, fold(46, s["name"]), fold(62, b["name"])),  # 머리 줄, 상호 줄
               max(7, fold(46, s["contact_name"]), fold(62, fmt_business_number(b["business_number"]))),
               max(7, fold(46, s["phone"]), fold(62, b["representative"]))]  # shortcut: 라벨 칸·이메일 줄은 한 줄로 본다, 라벨이 접히게 바꾸면 여기도 고친다
    po_h = fold(32, f"발주번호\n{doc['po_number']}\n\n발주일자\n{doc['order_date']}")  # 발주번호 칸 (rowspan=4) 글자 높이
    extra = max(0, po_h - sum(natural)) / 4  # 합친 칸이 모자란 높이를 네 행이 나눠 갖는다
    name_row_top = table_top + natural[0] + extra
    name_row_h = natural[1] + extra

    # 1) 수신처 | 발주번호·일자 | 발주처 (화면 표와 같은 5칸)
    with pdf.table(col_widths=(18, 46, 32, 22, 62), text_align="LEFT", line_height=7, first_row_as_headings=False) as t:
        row = t.row()
        row.cell("수신처", colspan=2, style=head, align="C")
        row.cell(f"발주번호\n{doc['po_number']}\n\n발주일자\n{doc['order_date']}", rowspan=4, align="C")
        row.cell("발주처", colspan=2, style=head, align="C")
        for left, right in (
            (("상 호", s["name"]), ("상 호", b["name"])),
            (("담당자", s["contact_name"]), ("사업자번호", fmt_business_number(b["business_number"]))),
            (("연락처", s["phone"]), ("대표자", b["representative"])),
        ):
            row = t.row()
            row.cell(left[0], style=head)
            row.cell(blank(left[1]))
            row.cell(right[0], style=head)
            row.cell(blank(right[1]))
        row = t.row()
        row.cell("이메일", style=head)
        row.cell(blank(s["email"]))
        row.cell("공급업체 정보", align="C")
        row.cell("담당자", style=head)
        row.cell(f"{b['author_name']} (작성자)")
        row = t.row()  # 발주처 연락처 (왼쪽 세 칸은 비운다, 화면과 같음)
        row.cell("", colspan=3)
        row.cell("연락처", style=head)
        row.cell(blank(b["phone"]))
        row = t.row()
        row.cell("주 소", colspan=2, style=head, align="C")
        row.cell(blank(b["address"]), colspan=3)

    pdf.ln(3)
    pdf.set_font("Nanum", "B", 11)
    fx = doc["currency"] != "KRW"
    pdf.multi_cell(0, 9, f"합계금액 : {money_text(doc, doc['total'], True)} (부가세 제외)" if fx
                   else f"합계금액 : 일금 {doc['total_korean']} 원정 (₩{doc['total']:,}), 부가세 포함", border=1, align="C",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Nanum", "", 9.5)

    # 2) 품목 표: 숫자 칸은 오른쪽 정렬
    widths = (10, 62, 14, 18, 22, 28, 26)
    aligns = ("C", "L", "C", "R", "R", "R", "L")
    with pdf.table(col_widths=widths, line_height=7, headings_style=head, text_align="CENTER") as t:
        cur = f" ({doc['currency']})" if fx else ""  # 외화 표는 열 머리에 통화를 적는다
        t.row(["No.", "품목명 (SKU)", "단위", "수량", f"단가{cur}", f"공급가액{cur}", "비고"])
        for line in doc["lines"]:
            values = (str(line["no"]), f"{line['product_name']} ({line['product_sku']})", line["unit"],
                      f"{line['quantity']:,}", money_text(doc, line["unit_price"]), money_text(doc, line["amount"]), line["note"])
            row = t.row()
            for value, align in zip(values, aligns, strict=True):
                row.cell(value, align=align)
        for _ in range(PDF_MIN_ROWS - len(doc["lines"])):  # 품목이 적으면 빈 줄로 채워 양식 모양을 유지한다 (화면과 같음)
            row = t.row()
            for _ in aligns:
                row.cell("")
        totals = ((("합계 (부가세 제외)", doc["total"]),) if fx else
                  (("공급가액 합계", doc["supply_total"]), ("부가세 (10%)", doc["vat"]), ("합계", doc["total"])))
        for label, value in totals:
            row = t.row()
            row.cell(label, colspan=5, style=head, align="C")
            row.cell(money_text(doc, value, fx), colspan=2, align="R")

    pdf.ln(3)
    # 3) 발주 조건 ~ 승인 줄: 쪽 경계에서 갈리지 않게 한 묶음으로 그린다
    with pdf.unbreakable() as block:  # 반드시 block 으로 그려야 쪽이 넘어갈 때 다시 그려진다 (pdf 로 직접 그리면 사라짐)
        with block.table(col_widths=(18, 162), line_height=7, text_align="LEFT", first_row_as_headings=False) as t:
            conditions = condition_rows(doc)  # 운송조건·특약은 값이 있을 때만 줄이 늘어난다
            for index, (label, value) in enumerate(conditions):
                row = t.row()
                if index == 0:
                    row.cell("발주\n조건", rowspan=len(conditions), style=head, align="C")
                row.cell(f"{index + 1}) {label} : {blank(value)}")

        block.ln(6)
        block.cell(0, 8, "위와 같이 발주합니다.", align="C", new_x="LMARGIN", new_y="NEXT")
        ap = doc["approval"]  # 승인 기록 (#263): 이름·시각이 없으면 "-"
        block.cell(0, 6, f"승인 : {ap['approver_name'] or '-'} · {ap['approved_at'] or '-'} (전자 승인 표시)", align="C",
                 new_x="LMARGIN", new_y="NEXT")
        if ap["company_name"] != b["name"]:  # 승인 뒤 상호가 바뀐 경우에만 한 줄 더
            block.cell(0, 6, f"(승인 시점 상호 : {ap['company_name']})", align="C", new_x="LMARGIN", new_y="NEXT")

    # 4) 도장: 표를 다 그린 뒤 1쪽 맨 위에 찍는다 (unbreakable 안에서는 local_context 를 못 쓴다)
    last_page = pdf.page
    pdf.page = 1
    draw_stamp(pdf, doc["approval"]["stamp"], PDF_TABLE_RIGHT - 0.5 - PDF_STAMP_D / 2,
               name_row_top + name_row_h / 2 - 0.08 * PDF_STAMP_D)
    pdf.page = last_page
    return pdf


def build_pdf(doc: dict) -> bytes:
    """문서 응답과 같은 값으로 PDF 를 만든다 (메일 첨부용). 그리는 일은 render_pdf 가 한다. 파일 속성(제목·작성자)은 넣지 않는다(#281)."""
    return bytes(render_pdf(doc).output())
