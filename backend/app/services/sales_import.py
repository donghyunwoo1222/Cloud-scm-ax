"""판매 가져오기 (#154): 쇼핑몰 주문 파일(CSV·엑셀)을 읽어 SALE 출고 이력으로 쌓는다.

서버는 올린 파일을 기억하지 않는다(디스크에 저장하지 않고 메모리에서만 처리).
그래서 열 확인(inspect) · 미리보기(preview) · 반영(commit)이 같은 파일과 설정을 매번 다시 받아 새로 계산한다.
특정 쇼핑몰의 열 이름·상태 값은 코드에 두지 않는다. 열은 사용자가 고른다(미리 선택 힌트만 일반적인 낱말로 준다).
"""

import csv  # CSV 읽기
import io  # 메모리 위의 파일 (디스크에 저장하지 않는다)
import re  # 날짜·수량 글자 모양 검사
from collections import Counter, defaultdict  # 개수 세기, 기본값이 있는 묶음
from dataclasses import dataclass  # 행 한 줄을 담는 작은 틀
from datetime import date, datetime  # 날짜

from openpyxl import load_workbook  # .xlsx 읽기
from sqlalchemy import select  # SELECT 문
from sqlalchemy.exc import IntegrityError  # DB 유일 제한 위반
from sqlalchemy.orm import Session  # DB 세션

from app.clock import date_problem, seoul_today  # 입출고일 공통 검사(미래·5년 하한), 서울 기준 오늘
from app.errors import AppError  # 공통 오류
from app.models import InventoryMovement, Product  # 이력, 품목
from app.schemas.sales_import import SalesImportOptions  # 열 지정·옵션
from app.services import stock as stock_service  # 이력은 register_movement 로만 쓴다

MAX_BYTES = 5 * 1024 * 1024  # 파일 크기 상한 5MB
MAX_ROWS = 5000  # 데이터 행 상한 (머리글 제외)
MAX_QUANTITY = 1_000_000  # 한 줄 수량 상한 (입출고 등록과 같은 규칙)
MAX_PROBLEMS_SHOWN = 200  # 응답에 담는 문제 행 목록 길이 (전체 개수는 따로 준다)
MAX_STATUS_VALUES = 50  # 상태 값 목록 상한 (고유 값이 이보다 많으면 상태 열로 부적합)

# 열 미리 선택 힌트: 일반적인 낱말일 뿐 특정 쇼핑몰 형식이 아니다. 앞쪽 낱말이 우선이다 (예: "상품주문번호"가 "주문번호"보다 먼저)
HINTS = {
    "product_col": ["상품코드", "상품 코드", "품목코드", "sku", "판매자상품코드", "상품번호"],
    "quantity_col": ["수량", "qty", "quantity"],
    "date_col": ["발송일", "주문일", "날짜", "일시", "date"],
    "ref_col": ["상품주문번호", "주문번호", "order"],
    "status_col": ["주문상태", "상태", "status"],
    "option_col": ["옵션", "option"],
}

PROBLEM_MESSAGES = {  # 문제 행 사유 → 화면에 보일 문장
    "MISSING_SKU": "상품 코드가 비어 있습니다.",
    "INVALID_QUANTITY": "수량이 1 이상의 정수가 아닙니다.",
    "INVALID_DATE": "날짜를 읽을 수 없습니다.",
    "FUTURE_DATE": "오늘 이후 날짜입니다.",
    "TOO_OLD_DATE": "5년보다 이전 날짜입니다. 연도를 확인해 주세요.",
    "MISSING_REF": "고유 주문번호가 비어 있거나 너무 깁니다.",
    "DUPLICATE_REF_IN_FILE": "파일 안에서 주문번호가 앞의 행과 겹칩니다.",
    "UNKNOWN_SKU": "등록되지 않은 상품 코드(SKU)입니다.",
    "INSUFFICIENT_STOCK": "날짜순으로 적용하면 재고가 부족해집니다.",
}
SKIP_MESSAGES = {  # 건너뜀 사유 → 화면에 보일 문장
    "STATUS_NOT_SELECTED": "반영하기로 고르지 않은 상태",
    "ALREADY_IMPORTED": "이미 반영된 주문번호",
}


def invalid(code: str, message: str, status: int = 422) -> AppError:
    return AppError(status, code, message)


# ---------- 1) 파일 읽기 ----------

def _cell_text(value) -> str:
    """셀 값을 글자로. 엑셀의 날짜·정수형 실수는 보기 좋은 글자로 바꾼다 (예: 3.0 → "3")."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()  # 엑셀 날짜 칸 → 2026-11-01
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def read_table(filename: str, content: bytes) -> tuple[list[str], list[list[str]]]:
    """파일 → (머리글, 데이터 행들). 크기·행 수·형식 검사를 여기서 한다."""
    if len(content) > MAX_BYTES:
        raise invalid("FILE_TOO_LARGE", "파일은 5MB 이하여야 합니다.")
    name = (filename or "").lower()
    if name.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")  # UTF-8 (BOM 이 있으면 떼어 낸다)
        except UnicodeDecodeError:
            try:
                text = content.decode("cp949")  # 한국 엑셀이 저장한 CSV
            except UnicodeDecodeError:
                raise invalid("INVALID_FILE", "CSV 인코딩을 읽을 수 없습니다. UTF-8로 저장해 올려 주세요.") from None
        table = list(csv.reader(io.StringIO(text)))
    elif name.endswith(".xlsx"):
        try:
            workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)  # 읽기 전용: 메모리를 아낀다
            sheet = workbook.worksheets[0]  # 첫 시트만 읽는다
            table = []
            for row in sheet.iter_rows(values_only=True):
                table.append([_cell_text(v) for v in row])
                if len(table) > MAX_ROWS + 1:  # 한도를 넘으면 더 읽지 않는다
                    break
        except Exception:  # noqa: BLE001 - openpyxl 이 파일 모양에 따라 여러 종류 예외를 내므로 모두 "읽을 수 없음"으로 처리
            raise invalid("INVALID_FILE", "엑셀(.xlsx) 파일을 읽을 수 없습니다.") from None
    else:
        raise invalid("INVALID_FILE", "CSV 또는 .xlsx 파일만 올릴 수 있습니다.")

    table = [row for row in table if any(c.strip() for c in row)]  # 완전히 빈 줄은 버린다
    if not table:
        raise invalid("INVALID_FILE", "파일이 비어 있습니다.")
    headers = [c.strip() for c in table[0]]
    rows = table[1:]
    if len(rows) > MAX_ROWS:
        raise invalid("TOO_MANY_ROWS", f"행은 {MAX_ROWS:,}개 이하여야 합니다.")
    return headers, rows


def suggest_columns(headers: list[str], hints: dict[str, list[str]] = HINTS) -> dict[str, int | None]:
    """머리글 이름이 비슷한 열을 미리 고르는 힌트. 낱말 우선순위대로 처음 맞는 열 (없으면 None)."""
    lowered = [h.lower() for h in headers]
    out: dict[str, int | None] = {}
    for key, words in hints.items():
        out[key] = next((i for w in words for i, h in enumerate(lowered) if w in h), None)
    return out


def inspect_file(filename: str, content: bytes, status_col: int | None) -> dict:
    """1단계: 머리글·행 수·열 미리 선택 힌트. 상태 열을 골랐을 때만 그 열의 값 목록(개수 포함)을 준다.

    다른 열의 값(수취인·주소 등)은 돌려주지 않는다 - 사용자가 고른 상태 열만 읽는다.
    """
    headers, rows = read_table(filename, content)
    result = {"headers": headers, "row_count": len(rows), "suggested": suggest_columns(headers), "status_values": None}
    if status_col is not None:
        if not 0 <= status_col < len(headers):
            raise invalid("VALIDATION_ERROR", "상태 열 번호가 파일에 없습니다.")
        counts = Counter(_get(r, status_col) for r in rows)
        if len(counts) > MAX_STATUS_VALUES:
            raise invalid("VALIDATION_ERROR", f"이 열은 값이 {MAX_STATUS_VALUES}종보다 많아 상태 열로 쓸 수 없습니다.")
        result["status_values"] = [{"value": v, "count": n} for v, n in sorted(counts.items())]
    return result


# ---------- 2) 행 해석 ----------

def _get(row: list[str], index: int) -> str:
    """행에서 열 하나. 줄이 짧아 칸이 없으면 빈 글자."""
    return row[index].strip() if index < len(row) else ""


_DATE_RE = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")  # 2026-11-01, 2026/11/1, 2026.11.01 (뒤의 시각은 무시)
_COMPACT_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")  # 20261101


def parse_date(text: str) -> date | None:
    """날짜 열 값을 날짜로. 시각은 버리고 그날 그대로 쓴다 (시간대 변환 없음). 못 읽으면 None."""
    m = _DATE_RE.match(text) or _COMPACT_DATE_RE.match(text)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:  # 2026-02-31 같은 없는 날짜
        return None


def parse_quantity(text: str) -> int | None:
    """수량 글자를 1~100만 정수로. 천 단위 쉼표는 허용(예: "1,200"). 아니면 None."""
    t = text.replace(",", "")
    if not t.isascii() or not t.isdigit():
        return None
    n = int(t)
    return n if 1 <= n <= MAX_QUANTITY else None


@dataclass
class Line:
    """파일의 한 행에서 읽어 낸 판매 한 줄."""

    row: int  # 파일 줄 번호 (머리글이 1, 첫 데이터가 2: 엑셀에서 보이는 번호)
    sku: str
    quantity: int
    day: date
    ref: str
    product_id: int | None = None  # SKU 로 찾은 우리 회사 품목


def analyze(company_id: int, db: Session, rows: list[list[str]], opts: SalesImportOptions, today: date) -> dict:
    """행들을 검사해 반영할 줄·건너뛸 줄·문제 줄을 가른다. DB 는 읽기만 한다.

    판단 순서(행 하나당 첫 번째 사유 하나만):
      상태 거르기(건너뜀) → 칸 값 검사(문제) → 파일 안 주문번호 중복(문제) → 이미 반영된 번호(건너뜀)
      → 미등록 SKU(문제) → 날짜순 누적 재고가 음수(문제)
    """
    skipped: Counter = Counter()  # 사유별 건너뜀 개수
    problems: list[dict] = []  # 문제 행 (행 번호, 사유)
    candidates: list[Line] = []  # 칸 검사를 통과한 줄
    selected = set(opts.statuses or [])
    seen_refs: set[str] = set()  # 파일에서 앞서 나온 주문번호
    option_values: dict[str, set[str]] = defaultdict(set)  # SKU 별 옵션 값 종류

    def problem(row_no: int, reason: str, sku: str | None = None) -> None:
        problems.append({"row": row_no, "reason": reason, "message": PROBLEM_MESSAGES[reason], "sku": sku})

    for offset, row in enumerate(rows):
        row_no = offset + 2  # 머리글이 1줄이라 첫 데이터 행은 2
        if opts.status_col is not None and _get(row, opts.status_col) not in selected:
            skipped["STATUS_NOT_SELECTED"] += 1  # 반영하기로 고르지 않은 상태 (상태 열이 없으면 모두 반영)
            continue
        sku = _get(row, opts.product_col).upper()  # SKU 는 대문자로 비교한다 (품목 규칙과 같다)
        quantity = parse_quantity(_get(row, opts.quantity_col))
        day = parse_date(_get(row, opts.date_col))
        ref = _get(row, opts.ref_col)
        if not sku:
            problem(row_no, "MISSING_SKU")
        elif quantity is None:
            problem(row_no, "INVALID_QUANTITY", sku)
        elif day is None:
            problem(row_no, "INVALID_DATE", sku)
        elif bad_date := date_problem(day, today):
            problem(row_no, bad_date, sku)  # 수동 등록과 같은 규칙: 미래·5년보다 이른 날짜는 안 받는다
        elif not ref or len(ref) > 100:
            problem(row_no, "MISSING_REF", sku)
        elif ref in seen_refs:
            problem(row_no, "DUPLICATE_REF_IN_FILE", sku)  # 앞의 행은 유지하고 뒤의 겹친 행만 막는다
        else:
            seen_refs.add(ref)
            candidates.append(Line(row_no, sku, quantity, day, ref))
            if opts.option_col is not None and _get(row, opts.option_col):
                option_values[sku].add(_get(row, opts.option_col))

    # 이미 반영된 주문번호는 건너뜀 (같은 파일을 다시 올려도 두 번 반영되지 않는다)
    existing = set(db.scalars(
        select(InventoryMovement.external_ref).where(
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.movement_type == "SALE",  # 번호는 유형마다 따로 센다 (입고 번호와 겹쳐도 무관, #155)
            InventoryMovement.external_ref.in_([c.ref for c in candidates]),
        )
    )) if candidates else set()
    fresh = []
    for c in candidates:
        if c.ref in existing:
            skipped["ALREADY_IMPORTED"] += 1
        else:
            fresh.append(c)

    # SKU → 우리 회사 품목 (다른 회사 SKU 는 여기서 찾아지지 않아 미등록으로 처리된다)
    product_ids = dict(db.execute(
        select(Product.sku, Product.id).where(
            Product.company_id == company_id, Product.sku.in_({c.sku for c in fresh}),
        )
    ).all()) if fresh else {}
    known = []
    for c in fresh:
        c.product_id = product_ids.get(c.sku)
        if c.product_id is None:
            problem(c.row, "UNKNOWN_SKU", c.sku)
        else:
            known.append(c)

    # 날짜순 누적: 품목마다 현재고에서 시작해 (날짜, 행 번호) 순서로 빼 가며 음수가 되는 줄을 찾는다.
    # 예) 현재고 10, 11/01 판매 6, 11/02 판매 7 → 11/01 은 10-6=4 통과, 11/02 는 4-7=-3 이라 문제.
    # 문제 줄은 재고를 쓰지 않은 것으로 치고 다음 줄을 계속 본다 (제외하고 반영할 때의 결과와 같아야 하므로).
    stocks = {r["product_id"]: r["current_stock"] for r in _stock_of(company_id, db, set(product_ids.values()))}
    running = dict(stocks)
    to_apply: list[Line] = []
    for c in sorted(known, key=lambda c: (c.day, c.row)):
        if running[c.product_id] - c.quantity < 0:
            problem(c.row, "INSUFFICIENT_STOCK", c.sku)
        else:
            running[c.product_id] -= c.quantity
            to_apply.append(c)

    problems.sort(key=lambda p: p["row"])
    # 같은 상품 코드에 옵션 값이 2종 이상 섞이면 경고 (반영에는 쓰지 않는다)
    warnings = [
        {"sku": sku, "option_count": len(values),
         "message": f"{sku}: 옵션 {len(values)}종이 하나의 SKU로 합산됩니다."}
        for sku, values in sorted(option_values.items()) if len(values) >= 2
    ]
    days = [c.day for c in to_apply]
    return {
        "to_apply": sorted(to_apply, key=lambda c: (c.day, c.row)),
        "problems": problems,
        "skipped": dict(skipped),
        "warnings": warnings,
        "date_from": min(days) if days else None,
        "date_to": max(days) if days else None,
        "total_quantity": sum(c.quantity for c in to_apply),
    }


def _stock_of(company_id: int, db: Session, product_ids: set[int]) -> list[dict]:
    """품목들의 현재고를 한 번에 (stock_rows 재사용)."""
    products = list(db.scalars(select(Product).where(Product.company_id == company_id, Product.id.in_(product_ids)))) if product_ids else []
    return stock_service.stock_rows(company_id, db, products)


def summarize(result: dict, total_rows: int) -> dict:
    """analyze 결과를 응답용 요약으로 (반영할 줄 목록 자체는 담지 않는다)."""
    skipped = [{"reason": r, "message": SKIP_MESSAGES[r], "count": n} for r, n in result["skipped"].items()]
    return {
        "total_rows": total_rows,
        "apply_count": len(result["to_apply"]),
        "skipped": skipped,
        "skipped_count": sum(s["count"] for s in skipped),
        "date_from": result["date_from"],
        "date_to": result["date_to"],
        "total_quantity": result["total_quantity"],
        "problem_count": len(result["problems"]),
        "problems": result["problems"][:MAX_PROBLEMS_SHOWN],
        "warnings": result["warnings"],
    }


# ---------- 3) 미리보기·반영 ----------

def _check_columns(headers: list[str], opts: SalesImportOptions) -> None:
    """지정한 열 번호가 파일 안에 있는지, 필수 열끼리 겹치지 않는지 검사 (어기면 422)."""
    used = [opts.product_col, opts.quantity_col, opts.date_col, opts.ref_col]
    extra = [c for c in (opts.status_col, opts.option_col) if c is not None]
    if any(not 0 <= c < len(headers) for c in used + extra):
        raise invalid("VALIDATION_ERROR", "지정한 열이 파일에 없습니다.")
    if len(set(used)) != len(used):
        raise invalid("VALIDATION_ERROR", "상품 코드·수량·날짜·주문번호는 서로 다른 열이어야 합니다.")


def preview(company_id: int, db: Session, filename: str, content: bytes, opts: SalesImportOptions) -> dict:
    """2단계: 미리보기. 아무것도 쓰지 않는다."""
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    result = analyze(company_id, db, rows, opts, seoul_today())
    return summarize(result, len(rows))


def commit(company_id: int, db: Session, user_id: int, filename: str, content: bytes, opts: SalesImportOptions) -> dict:
    """3단계: 반영. SALE 이력을 한 트랜잭션으로 쌓는다 (commit 은 호출한 API 가 한 번만 한다).

    미리보기 이후 재고가 바뀌었을 수 있으므로 화면의 결과를 믿지 않고 여기서 다시 계산한다.
    잠금 순서: 품목 번호 오름차순 (두 가져오기가 서로 반대 순서로 잠가 멈추는 일을 막는다).
    """
    if opts.sales_channel is None:
        raise AppError(422, "VALIDATION_ERROR", "판매 채널을 골라 주세요.", [{"field": "sales_channel", "reason": "required"}])
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    today = seoul_today()

    # ① 이번 파일에 나오는 품목을 번호순으로 먼저 전부 잠근다. 잠그기 전에 계산하면 그 사이 다른 출고가 끼어들 수 있다.
    skus = {_get(r, opts.product_col).upper() for r in rows} - {""}
    if skus:
        db.execute(
            select(Product.id).where(Product.company_id == company_id, Product.sku.in_(skus))
            .order_by(Product.id).with_for_update()
        ).all()  # FOR UPDATE: 결과가 번호순이라 잠금도 번호순
    # ② 잠근 뒤에 계산한다 (먼저 끝난 다른 요청의 재고·주문번호가 반영된 값을 본다)
    result = analyze(company_id, db, rows, opts, today)
    if result["problems"] and not opts.exclude_problems:
        raise AppError(409, "IMPORT_HAS_PROBLEMS", f"문제 행이 {len(result['problems'])}건 있어 반영할 수 없습니다.",
                       {"problem_count": len(result["problems"])})
    if not result["to_apply"]:
        raise AppError(409, "NOTHING_TO_IMPORT", "반영할 행이 없습니다.")
    # ③ 날짜순으로 한 줄씩 기존 출고 함수로 쓴다 (음수 검사·품목 잠금 규칙 그대로)
    try:
        for c in result["to_apply"]:
            stock_service.register_movement(
                company_id, db, user_id,
                product_id=c.product_id, movement_type="SALE", direction="OUT", quantity=c.quantity,
                movement_date=c.day, sales_channel=opts.sales_channel, external_ref=c.ref,
            )
    except IntegrityError:  # 다른 품목 잠금 아래 같은 주문번호가 동시에 들어온 드문 경우: DB 유일 제한이 막는다
        raise AppError(409, "DUPLICATE_REF", "같은 주문번호가 동시에 반영되었습니다. 미리보기부터 다시 하세요.") from None
    summary = summarize(result, len(rows))
    return {"imported_count": len(result["to_apply"]), **{k: summary[k] for k in (
        "skipped", "skipped_count", "problem_count", "date_from", "date_to", "total_quantity")}}
