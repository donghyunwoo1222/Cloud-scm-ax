"""목록 내보내기 (#191): 화면 목록과 같은 조건의 모든 행을 CSV·엑셀(.xlsx) 파일로 내려준다.

- 필터를 새로 만들지 않는다. 화면 목록이 쓰는 서비스 함수를 1,000개씩 끝까지 다시 부른다(화면과 파일이 같은 조건).
- 회사는 호출한 경로가 넘긴 토큰 사용자의 company_id 만 쓴다.
- 열은 대상별로 직접 적은 허용 목록만 쓴다(응답 객체를 통째로 쓰지 않아 새 칸이 저절로 새어 나가지 않는다).
- 엑셀 수식 주입 방어: 위험한 글자로 시작하는 글자 칸은 CSV 는 앞에 ' 를 붙이고, xlsx 는 문자열 칸으로 저장한다.
- 기록은 로그 한 줄뿐이다(파일 내용·검색어는 남기지 않는다). 서버 재시작·로그 정리로 사라질 수 있다.
"""

import csv  # CSV 쓰기
import io  # 메모리 위의 파일
import logging  # 내보내기 기록 한 줄
from collections.abc import Callable, Iterator  # 함수·반복자 타입

from fastapi import Response  # 엑셀 파일 응답
from fastapi.responses import StreamingResponse  # CSV 를 조금씩 보내는 응답
from openpyxl import Workbook  # .xlsx 쓰기 (이미 쓰는 라이브러리)
from openpyxl.cell import WriteOnlyCell  # 쓰기 전용 모드의 칸 (칸 형식을 직접 정할 때)
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import seoul_today  # 파일 이름의 날짜 (서울 기준)
from app.errors import AppError  # 공통 오류
from app.models import User  # 로그인 사용자
from app.pagination import PageParams  # 쪽 번호·쪽 크기
from app.services import products as products_service  # 품목 목록 (화면과 같은 조건)

log = logging.getLogger(__name__)  # 이 파일의 로그

MAX_ROWS = 50_000  # 한 번에 내보낼 수 있는 행 상한 (서버 보호용, 2026-11-15 사용자 결정. 측정 후 조정)
CHUNK = 1_000  # 한 번에 DB 에서 읽는 행 수 (메모리를 아끼려고 나눠 읽는다)

# 셀 값이 이 글자로 시작하면 엑셀이 수식으로 읽을 수 있다 (OWASP CSV Injection: = + - @ 탭 CR).
# 줄바꿈과 전각 ＝＋－＠ 도 함께 막는다(전각을 엑셀이 실행하는지는 확인 못함, 막는 비용이 거의 없어 넣었다)
FORMULA_START = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CSV = "text/csv; charset=utf-8"

# 품목 마스터: 앞 13열은 가져오기 템플릿(#189, import_templates.PRODUCT_HEADERS)과 같은 순서·이름이어야 다시 가져올 수 있다
PRODUCT_HEADERS = ["SKU", "품목명", "기본단위", "구매단가", "안전재고", "발주단위 이름", "환산계수", "발주단위 단가",
                   "최소 주문량", "색상", "사이즈", "규격", "그룹 코드", "기본 공급업체", "활성"]  # 끝 2열은 참고용 (가져오기는 무시)


def csv_text(value):
    """CSV 칸 하나. 위험한 글자로 시작하는 글자는 앞에 ' 를 붙여 엑셀이 글자로 보게 한다. 예) "=1+1" → "'=1+1".

    숫자(int)는 그대로 둔다: -5 는 숫자라 수식이 아니고, 글자로 바꾸면 엑셀 합계가 깨진다.
    """
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


def xlsx_cell(ws, value):
    """엑셀 칸 하나. 글자는 항상 문자열 칸(s)으로 저장한다.

    openpyxl 은 "=" 로 시작하는 글자를 수식 칸으로 바꾸므로 형식을 문자열로 되돌린다. 값은 그대로라 ' 가 붙지 않는다.
    한계(가능성): 문자열 칸이어도 사용자가 그 칸을 직접 고쳐 Enter 를 누르면 엑셀이 수식으로 다시 읽을 가능성이 있다.
    """
    if not isinstance(value, str):
        return value  # 숫자·빈칸은 그대로 (숫자 칸)
    cell = WriteOnlyCell(ws, value)
    cell.data_type = "s"  # 수식(f)이 아니라 문자열(s)
    return cell


def _csv_stream(headers: list[str], rows: Iterator[list]) -> Iterator[bytes]:
    """CSV 를 1,000행 단위로 만들어 바로 보낸다. 첫 조각에 BOM 을 붙여 엑셀에서 한글이 깨지지 않게 한다."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([csv_text(h) for h in headers])
    yield out.getvalue().encode("utf-8-sig")  # BOM + 머리글 (BOM 은 첫 조각에만)
    out.seek(0)
    out.truncate()  # 보낸 조각은 비운다
    for count, row in enumerate(rows, 1):
        writer.writerow([csv_text(v) for v in row])
        if count % CHUNK == 0:  # 1,000행마다 보낸다
            yield out.getvalue().encode("utf-8")
            out.seek(0)
            out.truncate()
    if out.tell():  # 마지막 남은 조각
        yield out.getvalue().encode("utf-8")


def _xlsx_bytes(headers: list[str], rows: Iterator[list]) -> bytes:
    """쓰기 전용 모드로 엑셀을 만든다(칸 객체를 메모리에 쌓지 않음). zip 이라 끝까지 만든 뒤 한 번에 보낸다."""
    wb = Workbook(write_only=True)
    ws = wb.create_sheet()
    ws.append([xlsx_cell(ws, h) for h in headers])
    for row in rows:
        ws.append([xlsx_cell(ws, v) for v in row])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def export(
    user: User, target: str, fmt: str, headers: list[str],
    fetch: Callable[[PageParams], tuple[list, dict]],  # 화면 목록과 같은 서비스 함수 (한 쪽 + meta)
    to_rows: Callable[[list], list[list]],  # 한 쪽의 행들 → 파일 행들
) -> Response:
    """첫 쪽에서 전체 개수를 보고 상한을 넘으면 파일을 만들기 전에 422. 아니면 끝까지 읽어 파일로 보낸다."""
    first, meta = fetch(PageParams(page=1, page_size=CHUNK))
    total = meta["total"]
    if total > MAX_ROWS:  # 스트리밍이 시작되면 오류 코드를 보낼 수 없어 먼저 센다
        log.info("export target=%s fmt=%s company_id=%s user_id=%s rows=%d outcome=TOO_LARGE", target, fmt, user.company_id, user.id, total)
        raise AppError(422, "EXPORT_TOO_LARGE", f"내보낼 행이 {total:,}개로 한 번에 내보낼 수 있는 {MAX_ROWS:,}개를 넘습니다. "
                       "검색어나 조건을 좁혀 주세요.", [{"field": "rows", "reason": "too_large"}])
    company_id, user_id = user.company_id, user.id  # 스트리밍 중에 사용자 객체를 다시 읽지 않게 미리 꺼낸다
    written = 0

    def rows() -> Iterator[list]:
        nonlocal written
        batch, page = first, 1
        while batch:
            for row in to_rows(batch):
                written += 1
                yield row
            if page * CHUNK >= total:  # 예) 2,500행 → 3쪽에서 끝
                break
            page += 1
            batch, _ = fetch(PageParams(page=page, page_size=CHUNK))

    def logged(outcome: str) -> None:
        # 한 줄만 남긴다: 누가·언제(로그 시각)·무엇·몇 행. 파일 내용·검색어·이메일은 남기지 않는다
        log.info("export target=%s fmt=%s company_id=%s user_id=%s rows=%d outcome=%s", target, fmt, company_id, user_id, written, outcome)

    filename = f"{target}-{seoul_today():%Y%m%d}.{fmt}"  # 영문·숫자만 (한글 파일 이름 인코딩 문제를 피한다)
    headers_out = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if fmt == "xlsx":
        content = _xlsx_bytes(headers, rows())
        logged("OK")
        return Response(content, media_type=XLSX, headers=headers_out)

    def streamed() -> Iterator[bytes]:
        outcome = "ERROR"
        try:
            yield from _csv_stream(headers, rows())
            outcome = "OK"
        finally:
            logged(outcome)  # 중간에 끊겨도 몇 행까지 보냈는지 남긴다

    return StreamingResponse(streamed(), media_type=CSV, headers=headers_out)


def products(
    user: User, db: Session, fmt: str, include_inactive: bool, q: str | None,
    default_supplier_id: int | None, group_code: str | None,
) -> Response:
    """품목 마스터. 화면 품목 목록(list_products)과 같은 조건·순서(최신순)."""
    company_id = user.company_id  # 회사는 토큰 사용자에게서만

    def fetch(page: PageParams):
        return products_service.list_products(company_id, db, page, include_inactive, q,
                                              default_supplier_id=default_supplier_id, group_code=group_code)

    def to_rows(batch: list) -> list[list]:
        suppliers = products_service.suppliers_of(company_id, db, batch)  # 쪽마다 한 번에
        # 발주단위 칸은 DB 원래 값을 쓴다. 화면 응답처럼 "없으면 기본단위·1"로 채우면 다시 가져올 때
        # "환산계수 1 + 발주단위 단가 없음" 문제 행(BOX_SETTINGS_INCOMPLETE)이 된다
        return [[p.sku, p.name, p.unit, p.unit_cost, p.safety_stock, p.order_unit, p.units_per_box, p.box_unit_cost,
                 p.min_order_units, p.color, p.size, p.spec, p.group_code,
                 suppliers[p.default_supplier_id].name, "활성" if p.is_active else "비활성"] for p in batch]

    return export(user, "products", fmt, PRODUCT_HEADERS, fetch, to_rows)
