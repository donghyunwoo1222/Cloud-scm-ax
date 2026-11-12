"""가져오기 템플릿 (#189): 머리글 + 예시 한 줄이 든 CSV·엑셀 파일을 만들어 준다. 새 라이브러리 없이 openpyxl·csv 만 쓴다."""

import csv  # CSV 쓰기
import io  # 메모리 위의 파일
from datetime import timedelta  # 예시 날짜 계산

from openpyxl import Workbook  # .xlsx 쓰기 (발주서 문서와 같은 방식)

from app.clock import seoul_today  # 서울 기준 오늘

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv; charset=utf-8"

PRODUCT_HEADERS = ["SKU", "품목명", "기본단위", "구매단가", "안전재고", "발주단위 이름", "환산계수", "발주단위 단가",
                   "최소 주문량", "색상", "사이즈", "규격", "그룹 코드"]
PRODUCT_EXAMPLE = ["EX-001", "예시 품목", "EA", 1200, 10, "BOX", 12, 13000, 1, "검정", "M", "2L", "EX-GROUP"]
SALES_HEADERS = ["상품 코드", "수량", "날짜", "고유 주문번호", "상태", "옵션"]


def _sales_example() -> list:
    """날짜는 5년 하한·미래 날짜 검사에 걸리지 않게 어제로 만든다."""
    return ["EX-001", 1, (seoul_today() - timedelta(days=1)).isoformat(), "ORDER-0001", "배송완료", "검정 / M"]


def build(kind: str, fmt: str) -> tuple[bytes, str]:
    """(파일 내용, 미디어 타입). kind 는 products|sales, fmt 는 xlsx|csv (호출한 API 가 먼저 검사한다)."""
    table = [PRODUCT_HEADERS, PRODUCT_EXAMPLE] if kind == "products" else [SALES_HEADERS, _sales_example()]
    if fmt == "csv":
        out = io.StringIO()
        csv.writer(out).writerows(table)
        return out.getvalue().encode("utf-8-sig"), CSV  # BOM 을 붙여야 엑셀에서 한글이 깨지지 않는다
    wb = Workbook()
    for row in table:
        wb.active.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue(), XLSX
