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
from datetime import date, datetime  # 날짜·시각 글자 만들기

from fastapi import Response  # 엑셀 파일 응답
from fastapi.responses import StreamingResponse  # CSV 를 조금씩 보내는 응답
from openpyxl import Workbook  # .xlsx 쓰기 (이미 쓰는 라이브러리)
from openpyxl.cell import WriteOnlyCell  # 쓰기 전용 모드의 칸 (칸 형식을 직접 정할 때)
from sqlalchemy import func, select  # 이름 조회, 발주 줄 개수
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL, seoul_today  # 서울 시간대, 파일 이름의 날짜
from app.errors import AppError  # 공통 오류
from app.models import (  # 로그인 사용자, 발주서, 공급업체
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.pagination import PageParams  # 쪽 번호·쪽 크기
from app.services import inventory_status  # 재고 목록 (화면과 같은 조건)
from app.services import products as products_service  # 품목 목록 (화면과 같은 조건)
from app.services import purchase_orders as po_service  # 발주서 목록·누적 입고량
from app.services import stock as stock_service  # 입출고 이력 목록
from app.services.tenant import scoped  # 회사 조건이 붙은 조회

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
    count_rows: Callable[[], int] | None = None,  # 목록 한 줄이 파일 여러 줄이 되면(발주서) 파일 행 수를 따로 센다
) -> Response:
    """첫 쪽에서 전체 개수를 보고 상한을 넘으면 파일을 만들기 전에 422. 아니면 끝까지 읽어 파일로 보낸다."""
    first, meta = fetch(PageParams(page=1, page_size=CHUNK))
    total = meta["total"]
    # 목록 개수가 상한 안이어도 파일 행은 더 많을 수 있다(발주서)
    total_rows = count_rows() if total <= MAX_ROWS and count_rows else total
    if total_rows > MAX_ROWS:  # 스트리밍이 시작되면 오류 코드를 보낼 수 없어 먼저 센다
        log.info("export target=%s fmt=%s company_id=%s user_id=%s rows=%d outcome=TOO_LARGE", target, fmt, user.company_id, user.id, total_rows)
        raise AppError(422, "EXPORT_TOO_LARGE", f"내보낼 행이 {total_rows:,}개로 한 번에 내보낼 수 있는 {MAX_ROWS:,}개를 넘습니다. "
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


def day(value: date | None) -> str | None:
    """날짜 칸 → YYYY-MM-DD 글자. 예) 2026-11-15 → "2026-11-15"."""
    return value.isoformat() if value else None


def seoul_time(value: datetime | None) -> str | None:
    """UTC 시각 → 서울 시간 "YYYY-MM-DD HH:MM". 예) 2026-11-15 00:30 UTC → "2026-11-15 09:30"."""
    return value.astimezone(SEOUL).strftime("%Y-%m-%d %H:%M") if value else None


def user_names(company_id: int, db: Session, ids: set) -> dict[int, str]:
    """사용자 id → 이름 (같은 회사만). 이메일·해시는 읽지 않는다."""
    ids.discard(None)
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.name).where(User.company_id == company_id, User.id.in_(ids))).all())


STOCK_HEADERS = ["SKU", "품목명", "현재고", "단위", "안전재고", "발주 진행 중 수량", "재주문점", "상태", "판단 불가 이유",
                 "색상", "사이즈", "규격", "그룹 코드", "활성"]
STATUS_LABELS = {"SHORTAGE": "부족", "NORMAL": "정상", "UNKNOWN": "판단 불가"}  # 비활성 품목은 상태 없음(빈칸)


def stock(
    user: User, db: Session, fmt: str, include_inactive: bool, status: str | None, q: str | None, group_code: str | None,
) -> Response:
    """재고 현황. 화면 재고 목록(list_stock)과 같은 조건·순서(최신순)."""
    company_id, today = user.company_id, seoul_today()
    cache: dict = {}  # 상태 필터가 있어도 전체 품목의 상태 계산은 한 번만 (쪽마다 다시 계산하지 않는다)

    def fetch(page: PageParams):
        return inventory_status.list_stock(company_id, db, today, page, include_inactive, status,
                                           q=q, group_code=group_code, cache=cache)

    def to_rows(batch: list) -> list[list]:
        return [[r["sku"], r["name"], r["current_stock"], r["unit"], r["safety_stock"], r["in_transit"],
                 None if r["reorder_point"] is None else round(r["reorder_point"], 1),
                 STATUS_LABELS.get(r["status"]), r["status_reason"]["message"] if r["status_reason"] else None,
                 r["color"], r["size"], r["spec"], r["group_code"], "활성" if r["is_active"] else "비활성"] for r in batch]

    return export(user, "stock", fmt, STOCK_HEADERS, fetch, to_rows)


MOVEMENT_HEADERS = ["입출고일", "SKU", "품목명", "유형", "방향", "수량", "단위", "판매 채널", "사유", "메모", "발주번호",
                    "등록자", "등록 시각"]
TYPE_LABELS = {"RECEIPT": "입고", "SALE": "판매", "DISPOSAL": "폐기", "OTHER_OUT": "기타 출고", "ADJUSTMENT": "실사 조정", "CORRECTION": "정정"}  # 화면(frontend movement-form.tsx TYPE_LABEL)과 같은 말
DIRECTION_LABELS = {"IN": "증가", "OUT": "감소"}


def movements(
    user: User, db: Session, fmt: str, product_id: int | None, movement_types: list[str] | None,
    date_from: date | None, date_to: date | None, sort: str,
) -> Response:
    """입출고 이력. 화면 이력 목록(list_movements)과 같은 조건·순서. 이력은 수정 불가라 정정도 한 줄로 그대로 나온다."""
    stock_service.check_period(date_from, date_to)  # 거꾸로 된 기간은 목록과 같은 422
    company_id = user.company_id

    def fetch(page: PageParams):
        return stock_service.list_movements(company_id, db, page, product_id, movement_types, date_from, date_to, sort)

    def to_rows(batch: list) -> list[list]:
        products, order_ids = stock_service.movement_links(company_id, db, batch)  # 쪽마다 한 번에
        po_numbers = dict(db.execute(select(PurchaseOrder.id, PurchaseOrder.po_number).where(
            PurchaseOrder.company_id == company_id, PurchaseOrder.id.in_(set(order_ids.values())))).all()) if order_ids else {}
        names = user_names(company_id, db, {m.created_by for m in batch})
        return [[day(m.movement_date), products[m.product_id].sku, products[m.product_id].name, TYPE_LABELS[m.movement_type],
                 DIRECTION_LABELS[m.direction], m.quantity, products[m.product_id].unit, m.sales_channel, m.reason, m.memo,
                 po_numbers.get(order_ids.get(m.purchase_order_item_id)), names.get(m.created_by), seoul_time(m.created_at)]
                for m in batch]

    return export(user, "movements", fmt, MOVEMENT_HEADERS, fetch, to_rows)


ORDER_HEADERS = ["발주번호", "상태", "공급업체", "납기", "메모", "납품장소", "지불조건", "작성자", "작성 시각", "승인자", "승인 시각",
                 "발주 시각", "입고 완료 시각", "취소 시각",
                 "통화", "환율", "운송비 조건", "운송비", "부대비용 합계", "특약", "품목 원화 합계", "원가",  # 원가 칸 (#267, 내부 전용 내보내기)
                 "SKU", "품목명", "발주단위 수량", "발주단위 이름", "환산계수",
                 "기본단위 수량", "기본단위 이름", "단가", "발주단위 단가", "금액", "외화 단가", "외화 발주단위 단가", "외화 금액",
                 "누적 입고량", "회신 납기"]


def orders(
    user: User, db: Session, fmt: str, supplier_id: int | None, status: str | None, q: str | None, receipt_due: str | None,
) -> Response:
    """발주서. 한 줄 = 발주 품목 한 줄(머리 정보는 줄마다 반복). 화면 발주서 목록(list_orders)과 같은 조건·순서.

    발주단위·환산계수는 발주 줄에 저장된 원래 값이다(발주단위가 없는 줄은 빈칸, 기본단위 수량만 있다).
    줄이 하나도 없는 발주서는 빈 품목 칸으로 한 줄 나온다(발주서가 파일에서 사라지지 않게).
    """
    company_id = user.company_id

    def fetch(page: PageParams):
        return po_service.list_orders(company_id, db, page, supplier_id, status, q, receipt_due)

    def count_rows() -> int:
        """파일 행 수 = 줄 수(줄 없는 발주서는 1). 목록을 끝까지 넘기며 센다. 상한을 넘으면 거기서 멈춘다."""
        total, page = 0, 1
        while True:
            batch, meta = fetch(PageParams(page=page, page_size=CHUNK))
            ids = [o.id for o in batch]
            per_order = dict(db.execute(select(PurchaseOrderItem.purchase_order_id, func.count()).where(
                PurchaseOrderItem.company_id == company_id, PurchaseOrderItem.purchase_order_id.in_(ids),
            ).group_by(PurchaseOrderItem.purchase_order_id)).all()) if ids else {}
            total += sum(max(per_order.get(i, 0), 1) for i in ids)
            if total > MAX_ROWS or page * CHUNK >= meta["total"]:
                return total
            page += 1

    def to_rows(batch: list) -> list[list]:
        ids = [o.id for o in batch]
        items = list(db.scalars(scoped(company_id, PurchaseOrderItem).where(
            PurchaseOrderItem.purchase_order_id.in_(ids)).order_by(PurchaseOrderItem.id))) if ids else []
        products = {p.id: p for p in products_service.products_by_ids(company_id, db, {i.product_id for i in items})}
        suppliers = {s.id: s for s in db.scalars(scoped(company_id, Supplier).where(
            Supplier.id.in_({o.supplier_id for o in batch})))} if batch else {}
        received = po_service.received_quantities(company_id, db, [i.id for i in items])
        names = user_names(company_id, db, {u for o in batch for u in (o.created_by, o.approved_by)})
        by_order: dict[int, list] = {}
        for i in items:
            by_order.setdefault(i.purchase_order_id, []).append(i)
        rows = []
        for o in batch:
            head = [o.po_number, o.status, suppliers[o.supplier_id].name, day(o.due_date), o.memo, o.delivery_address, o.payment_terms,
                    names.get(o.created_by), seoul_time(o.created_at), names.get(o.approved_by), seoul_time(o.approved_at),
                    seoul_time(o.ordered_at), seoul_time(o.received_at), seoul_time(o.cancelled_at)]
            cost = po_service.cost_of(o, by_order.get(o.id, []), received)  # 화면 원가 카드와 같은 계산 (#267)
            head += [o.currency, o.exchange_rate, o.freight_terms, o.freight_amount, cost.extras_total, o.special_terms,
                     cost.goods_krw, cost.total]
            for i in by_order.get(o.id) or [None]:  # 줄이 없으면 빈 품목 칸 한 줄
                if i is None:
                    rows.append(head + [None] * (len(ORDER_HEADERS) - len(head) - 1) + [day(o.supplier_due_date)])
                    continue
                p = products[i.product_id]
                boxed = i.units_per_box is not None  # 발주단위 줄인가
                rows.append(head + [p.sku, p.name, i.quantity // i.units_per_box if boxed else None, i.order_unit, i.units_per_box,
                                    i.quantity, p.unit, i.unit_price, i.box_unit_price, po_service.line_total(i),
                                    i.fx_unit_price, i.fx_box_unit_price, po_service.fx_line_total(i), received.get(i.id, 0), day(o.supplier_due_date)])
        return rows

    return export(user, "purchase-orders", fmt, ORDER_HEADERS, fetch, to_rows, count_rows)
