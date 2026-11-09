"""발주서 문서(#157): 인쇄 화면과 엑셀이 같이 쓰는 값을 서버에서 한 번만 계산한다. 화면·엑셀 숫자가 어긋나지 않게 하려는 것."""

from io import BytesIO  # 엑셀을 메모리에서 만든다 (디스크 저장 없음)

from openpyxl import Workbook  # .xlsx 쓰기 (#154에서 설치한 라이브러리)
from openpyxl.styles import Alignment, Font  # 가운데 정렬·굵은 글씨
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL  # 서울 시간대 (발주일자)
from app.errors import AppError  # 공통 오류
from app.models import Company, Supplier, User  # 표들
from app.services import purchase_orders as po_service  # 발주서 조회·응답 만들기
from app.services.tenant import get_owned  # 회사 조건이 붙은 조회

DOCUMENT_STATUSES = ("APPROVED", "ORDERED", "RECEIVED")  # 승인 이후 상태만 문서를 만든다 (DRAFT·CANCELLED 는 409)
DIGITS = "영일이삼사오육칠팔구"  # 숫자 → 한글
SMALL_UNITS = ("", "십", "백", "천")  # 네 자리 묶음 안의 자릿수
BIG_UNITS = ("", "만", "억", "조", "경")  # 네 자리 묶음 이름


def vat_of(supply_total: int) -> int:
    """부가세 = 공급가액 합계의 10%, 원 미만 버림 (줄별 세액 없음). 예) 1,005 → 100."""
    return supply_total // 10


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


def build_document(company_id: int, db: Session, order_id: int) -> dict:
    """GET /purchase-orders/{id}/document 응답. 다른 회사·없는 id 는 404, 승인 전·취소는 409. 회사 정보가 비어도 만들어진다."""
    order = po_service.get_order(company_id, db, order_id)  # 다른 회사 404
    if order.status not in DOCUMENT_STATUSES:
        raise AppError(409, "INVALID_STATUS", "승인된 발주서만 문서로 볼 수 있습니다.", {"status": order.status})
    out = po_service.build_out(company_id, db, [order])[0]  # 줄 금액은 발주서 응답과 같은 계산을 쓴다
    company = db.get_one(Company, company_id)
    supplier = get_owned(company_id, db, Supplier, order.supplier_id)
    author = get_owned(company_id, db, User, order.created_by)  # 작성자 (같은 회사 사용자)
    lines = []
    for number, item in enumerate(out["items"], start=1):
        boxed = item["box_quantity"] is not None  # 박스 발주는 박스 단위로 적는다
        lines.append({
            "no": number,
            "product_name": item["product_name"], "product_sku": item["product_sku"],
            "unit": "박스" if boxed else item["unit"],
            "quantity": item["box_quantity"] if boxed else item["quantity"],
            "unit_price": item["box_unit_price"] if boxed else item["unit_price"],
            "amount": item["line_total"],
            "note": f"1박스={item['units_per_box']:,}개" if boxed else "",
        })
    supply_total = sum(line["amount"] for line in lines)
    vat = vat_of(supply_total)
    total = supply_total + vat
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
        "supply_total": supply_total, "vat": vat, "total": total, "total_korean": korean_amount(total),
        "due_date": order.due_date.isoformat() if order.due_date else None,
        "delivery_address": order.delivery_address or company.address,  # 비면 회사 주소
        "payment_terms": order.payment_terms,
        "memo": order.memo,
    }


def build_xlsx(doc: dict) -> bytes:
    """문서 응답과 같은 값으로 엑셀 한 장을 만든다. 숫자는 숫자 칸으로 넣어 합계 계산에 쓸 수 있다."""
    wb = Workbook()
    ws = wb.active
    ws.title = doc["po_number"]
    bold = Font(bold=True)
    ws.append(["발 주 서"])
    ws["A1"].font = Font(bold=True, size=16)
    ws.append(["발주번호", doc["po_number"], "발주일자", doc["order_date"]])
    s, b = doc["supplier"], doc["buyer"]
    ws.append(["[수신처]"])
    ws.append(["상호", s["name"], "담당자", s["contact_name"], "연락처", s["phone"], "이메일", s["email"]])
    ws.append(["[발주처]"])
    ws.append(["상호", b["name"], "사업자번호", fmt_business_number(b["business_number"]), "대표자", b["representative"]])
    ws.append(["연락처", b["phone"], "주소", b["address"], "담당자(작성자)", b["author_name"]])
    ws.append([])
    ws.append([f"합계금액: 일금 {doc['total_korean']} 원정 (₩{doc['total']:,}, 부가세 포함)"])
    header_row = ws.max_row + 1
    ws.append(["No.", "품목명 (SKU)", "단위", "수량", "단가", "공급가액", "비고"])
    for cell in ws[header_row]:
        cell.font = bold
        cell.alignment = Alignment(horizontal="center")
    for line in doc["lines"]:
        ws.append([line["no"], f"{line['product_name']} ({line['product_sku']})", line["unit"], line["quantity"],
                   line["unit_price"], line["amount"], line["note"]])
    for label, value in (("공급가액 합계", doc["supply_total"]), ("부가세 (10%)", doc["vat"]), ("합계", doc["total"])):
        ws.append([None, None, None, None, label, value])
        ws.cell(ws.max_row, 5).font = bold
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):  # 수량·단가·금액 칸은 천 단위 쉼표
        for cell in row[3:6]:
            cell.number_format = "#,##0"
    ws.append([])
    ws.append(["발주 조건"])
    ws.append(["1) 납기일자", doc["due_date"]])
    ws.append(["2) 납품장소", doc["delivery_address"]])
    ws.append(["3) 지불조건", doc["payment_terms"]])
    ws.append(["4) 기타", doc["memo"]])
    for column, width in zip("ABCDEFGH", (14, 28, 10, 12, 16, 16, 20, 24), strict=True):
        ws.column_dimensions[column].width = width
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
