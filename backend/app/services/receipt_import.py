"""품목·입고 가져오기 (#155): 공급업체가 보낸 입고 목록 파일 하나로 새 품목 등록과 직접 입고(RECEIPT)를 한 번에 한다.

판매 가져오기(#154)의 틀을 그대로 쓴다: 파일은 저장하지 않고, 열 확인 → 미리보기 → 반영마다 파일을 다시 받아 새로 계산한다.
- 수량 열이 있으면 "입고" 모드: 기존 SKU 는 입고만, 없는 SKU 는 새 품목으로 등록한 뒤 입고한다 (같은 트랜잭션).
- 수량 열이 없으면 "품목만 등록" 모드: 없는 SKU 만 새 품목으로 등록하고 기존 SKU 는 건너뛴다 (기존 품목 정보는 고치지 않는다).
"""

from collections import Counter  # 개수 세기
from dataclasses import dataclass  # 행 한 줄을 담는 작은 틀
from datetime import date  # 날짜

from pydantic import ValidationError  # 새 품목 값 검사 실패
from sqlalchemy import func, select  # 합계, SELECT 문
from sqlalchemy.exc import IntegrityError  # DB 유일 제한 위반
from sqlalchemy.orm import Session  # DB 세션

from app.clock import date_problem, seoul_today  # 입출고일 공통 검사(미래·5년 하한), 서울 기준 오늘
from app.errors import AppError  # 공통 오류
from app.models import InventoryMovement, Product  # 이력, 품목
from app.schemas.receipt_import import NewProduct, ReceiptImportOptions  # 열 지정, 새 품목 값 규칙
from app.services import stock as stock_service  # 이력은 register_movement 로만 쓴다
from app.services.products import (
    check_default_supplier,  # 기본 공급업체 검사 (다른 회사 404, 비활성 409)
)
from app.services.sales_import import (  # 판매 가져오기의 파일 읽기·값 해석을 그대로 쓴다
    MAX_PROBLEMS_SHOWN,
    _get,
    invalid,
    parse_date,
    parse_quantity,
    read_table,
    suggest_columns,
)

HINTS = {  # 열 미리 선택 힌트 (일반 낱말만)
    "product_col": ["상품코드", "상품 코드", "품목코드", "sku", "상품번호"],
    "quantity_col": ["수량", "qty", "quantity"],
    "date_col": ["입고일", "납품일", "날짜", "일자", "date"],
    "ref_col": ["입고번호", "전표번호", "명세서번호", "문서번호"],
    "name_col": ["품목명", "상품명", "품명", "name"],
    "unit_col": ["단위", "unit"],
    "cost_col": ["단가", "매입가", "원가", "cost", "price"],
    "safety_col": ["안전재고", "safety"],
    "supplier_col": ["공급업체", "거래처", "매입처", "supplier", "vendor"],
}

PROBLEM_MESSAGES = {
    "MISSING_SKU": "상품 코드가 비어 있거나 50자를 넘습니다.",
    "INVALID_QUANTITY": "수량이 1 이상의 정수가 아닙니다.",
    "INVALID_DATE": "날짜를 읽을 수 없습니다.",
    "FUTURE_DATE": "오늘 이후 날짜입니다.",
    "TOO_OLD_DATE": "5년보다 이전 날짜입니다. 연도를 확인해 주세요.",
    "MISSING_REF": "고유 번호가 비어 있거나 너무 깁니다.",
    "DUPLICATE_REF_IN_FILE": "파일 안에서 고유 번호가 앞의 행과 겹칩니다.",
    "INVALID_PRODUCT_INFO": "새 품목인데 품목명·단위·단가(0 이상 정수)·안전재고 값이 비었거나 올바르지 않습니다.",
}
SKIP_MESSAGES = {
    "ALREADY_IMPORTED": "이미 반영된 입고",
    "PRODUCT_EXISTS": "이미 등록된 품목",
    "SAME_SKU_ABOVE": "위 행과 같은 SKU",
}


@dataclass
class Line:
    """파일 한 행에서 읽어 낸 한 줄 (품목만 모드면 수량·날짜·번호가 없다)."""

    row: int  # 파일 줄 번호 (머리글 1, 첫 데이터 2)
    sku: str
    cells: list[str]  # 원래 행 (새 품목 값을 읽을 때 쓴다)
    quantity: int | None = None
    day: date | None = None
    ref: str | None = None


def inspect_file(filename: str, content: bytes) -> dict:
    """1단계: 머리글·행 수·열 미리 선택 힌트 (값은 돌려주지 않는다)."""
    headers, rows = read_table(filename, content)
    return {"headers": headers, "row_count": len(rows), "suggested": suggest_columns(headers, HINTS)}


def _int_or_text(text: str) -> int | str:
    """단가·안전재고 글자 → 정수(천 단위 쉼표 허용). 정수가 아니면 글자 그대로 둬서 검사에서 걸리게 한다."""
    t = text.replace(",", "")
    return int(t) if t.isascii() and t.isdigit() else text


def _new_product(line: Line, opts: ReceiptImportOptions) -> NewProduct | None:
    """행에서 새 품목 값을 읽어 품목 등록과 같은 규칙으로 검사한다. 어긋나면 None."""
    cell = lambda col: _get(line.cells, col) if col is not None else ""
    values = {"sku": line.sku, "name": cell(opts.name_col), "unit": cell(opts.unit_col),
              "unit_cost": _int_or_text(cell(opts.cost_col))}
    if cell(opts.safety_col):  # 비어 있으면 기본 0
        values["safety_stock"] = _int_or_text(cell(opts.safety_col))
    try:
        return NewProduct(**values)
    except ValidationError:
        return None


def analyze(company_id: int, db: Session, rows: list[list[str]], opts: ReceiptImportOptions, today: date) -> dict:
    """행들을 검사해 새 품목·입고 줄·건너뜀·문제를 가른다. DB 는 읽기만 한다.

    판단 순서(행 하나당 첫 사유 하나): 칸 값 검사(문제) → 파일 안 번호 중복(문제) → 이미 반영(건너뜀)
      → 기존 품목이면 입고 / 없는 품목이면 그 SKU 첫 행의 새 품목 값 검사(어긋나면 그 SKU 의 모든 행이 문제)
    """
    receipts = opts.quantity_col is not None  # 수량 열이 있으면 입고 모드
    skipped: Counter = Counter()
    problems: list[dict] = []
    candidates: list[Line] = []
    seen_refs: set[str] = set()
    same_content: Counter = Counter()  # 번호 열이 없을 때 (날짜, SKU, 수량) 조합이 몇 번째인지

    def problem(line_row: int, reason: str, sku: str | None = None) -> None:
        problems.append({"row": line_row, "reason": reason, "message": PROBLEM_MESSAGES[reason], "sku": sku})

    for offset, row in enumerate(rows):
        line = Line(offset + 2, _get(row, opts.product_col).upper(), row)
        if not line.sku or len(line.sku) > 50:
            problem(line.row, "MISSING_SKU")
            continue
        if receipts:
            line.quantity = parse_quantity(_get(row, opts.quantity_col))
            line.day = parse_date(_get(row, opts.date_col))
            if line.quantity is None:
                problem(line.row, "INVALID_QUANTITY", line.sku)
                continue
            if line.day is None:
                problem(line.row, "INVALID_DATE", line.sku)
                continue
            if bad_date := date_problem(line.day, today):
                problem(line.row, bad_date, line.sku)  # 수동 입고와 같은 규칙 (미래·5년보다 이른 날짜)
                continue
            if opts.ref_col is not None:
                line.ref = _get(row, opts.ref_col)
                if not line.ref or len(line.ref) > 100:
                    problem(line.row, "MISSING_REF", line.sku)
                    continue
                if line.ref in seen_refs:
                    problem(line.row, "DUPLICATE_REF_IN_FILE", line.sku)
                    continue
                seen_refs.add(line.ref)
            else:
                # 번호 열이 없으면 내용으로 번호를 만든다. 같은 (날짜, SKU, 수량)이 두 번 나오면 1, 2 로 구분한다.
                # 예) 2026-11-01 TS-01 30개 두 행 → "2026-11-01|TS-01|30|1", "…|2". 행을 더하거나 순서를 바꿔 다시 올려도 같은 번호.
                key = (line.day, line.sku, line.quantity)
                same_content[key] += 1
                line.ref = f"{line.day.isoformat()}|{line.sku}|{line.quantity}|{same_content[key]}"
        candidates.append(line)

    # 이미 반영된 입고 번호는 건너뜀 (같은 파일을 다시 올려도 재고가 두 번 늘지 않는다)
    existing_refs = set(db.scalars(
        select(InventoryMovement.external_ref).where(
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.movement_type == "RECEIPT",  # 판매 주문번호와는 따로 센다
            InventoryMovement.external_ref.in_([c.ref for c in candidates]),
        )
    )) if receipts and candidates else set()
    fresh = []
    for c in candidates:
        if c.ref in existing_refs:
            skipped["ALREADY_IMPORTED"] += 1
        else:
            fresh.append(c)

    # SKU → 우리 회사 품목 (다른 회사 SKU 는 찾아지지 않아 새 품목 후보가 된다. 우리 회사에 새로 생길 뿐 남의 품목은 건드리지 않는다)
    product_ids = dict(db.execute(
        select(Product.sku, Product.id).where(Product.company_id == company_id, Product.sku.in_({c.sku for c in fresh}))
    ).all()) if fresh else {}

    new_products: dict[str, NewProduct | None] = {}  # 새 SKU → 첫 행에서 읽은 값 (어긋나면 None)
    new_product_rows: dict[str, int] = {}  # 새 SKU → 값을 읽은 행 번호
    to_apply: list[Line] = []
    for c in fresh:
        if c.sku in product_ids:
            if receipts:
                to_apply.append(c)  # 기존 품목: 입고만 (비활성 품목도 직접 입고는 허용, 원칙 8)
            else:
                skipped["PRODUCT_EXISTS"] += 1
            continue
        if c.sku not in new_products:  # 이 SKU 의 첫 행에서 새 품목 값을 읽는다
            new_products[c.sku] = _new_product(c, opts)
            new_product_rows[c.sku] = c.row
        elif not receipts:
            skipped["SAME_SKU_ABOVE"] += 1  # 품목만 모드: 같은 SKU 둘째 행부터는 할 일이 없다
            continue
        if new_products[c.sku] is None:
            problem(c.row, "INVALID_PRODUCT_INFO", c.sku)
        elif receipts:
            to_apply.append(c)

    problems.sort(key=lambda p: p["row"])
    valid_new = {sku: p for sku, p in new_products.items() if p is not None}  # 입고 모드면 첫 행이 곧 입고 줄이라 입고 없는 새 품목은 없다
    days = [c.day for c in to_apply]
    return {
        "warnings": _same_day_warnings(company_id, db, to_apply),
        "to_apply": sorted(to_apply, key=lambda c: (c.day, c.row)),
        "new_products": [{"row": new_product_rows[s], **p.model_dump()} for s, p in sorted(valid_new.items(), key=lambda x: new_product_rows[x[0]])],
        "problems": problems,
        "skipped": dict(skipped),
        "date_from": min(days) if days else None,
        "date_to": max(days) if days else None,
        "total_quantity": sum(c.quantity for c in to_apply),
    }


def _same_day_warnings(company_id: int, db: Session, to_apply: list[Line]) -> list[dict]:
    """새로 넣을 입고와 같은 날·같은 품목의 입고가 DB 에 이미 있으면 경고 (막지는 않는다).

    번호 열이 없는 파일에서 반영된 줄의 수량을 고쳐 다시 올리면 (50 → 55) 다른 입고로 보여 한 번 더 들어간다.
    시스템은 "고친 것"과 "같은 날 또 들어온 것"을 구분할 수 없어서 사람에게 묻는다. 수정이라면 정정 이력으로 바로잡아야 한다.
    """
    if not to_apply:
        return []
    existing = {(sku, day): qty for sku, day, qty in db.execute(
        select(Product.sku, InventoryMovement.movement_date, func.sum(InventoryMovement.quantity))
        .join(Product, Product.id == InventoryMovement.product_id)
        .where(
            InventoryMovement.company_id == company_id,  # 우리 회사 이력만 (R1)
            InventoryMovement.movement_type == "RECEIPT",  # 직접·발주 입고 모두 (정정은 보지 않는다)
            Product.sku.in_({c.sku for c in to_apply}),
            InventoryMovement.movement_date.in_({c.day for c in to_apply}),
        )
        .group_by(Product.sku, InventoryMovement.movement_date)
    ).all()}
    keys = sorted({(c.sku, c.day) for c in to_apply if (c.sku, c.day) in existing}, key=lambda k: (k[1], k[0]))
    return [{"sku": sku, "date": day, "existing_quantity": existing[(sku, day)],
             "message": f"{sku} {day.isoformat()}: 같은 날 입고 {existing[(sku, day)]:,}개가 이미 있습니다. "
                        "수량·날짜를 고쳐 다시 올린 거라면 그 줄을 파일에서 지우고, 원래 입고는 재고 현황에서 정정하세요."}
            for sku, day in keys[:MAX_PROBLEMS_SHOWN]]


def summarize(result: dict, total_rows: int) -> dict:
    """analyze 결과 → 응답용 요약 (입고 줄 목록 자체는 담지 않는다)."""
    skipped = [{"reason": r, "message": SKIP_MESSAGES[r], "count": n} for r, n in result["skipped"].items()]
    return {
        "total_rows": total_rows,
        "apply_count": len(result["to_apply"]),
        "new_product_count": len(result["new_products"]),
        "new_products": result["new_products"][:MAX_PROBLEMS_SHOWN],
        "skipped": skipped,
        "skipped_count": sum(s["count"] for s in skipped),
        "date_from": result["date_from"],
        "date_to": result["date_to"],
        "total_quantity": result["total_quantity"],
        "problem_count": len(result["problems"]),
        "problems": result["problems"][:MAX_PROBLEMS_SHOWN],
        "warnings": result["warnings"],
    }


def _check_columns(headers: list[str], opts: ReceiptImportOptions) -> None:
    """지정한 열이 파일 안에 있는지, 겹치지 않는지, 입고 모드면 날짜 열이 있는지 검사 (어기면 422)."""
    chosen = [c for c in (opts.product_col, opts.quantity_col, opts.date_col, opts.ref_col,
                          opts.name_col, opts.unit_col, opts.cost_col, opts.safety_col, opts.supplier_col) if c is not None]
    if any(c >= len(headers) for c in chosen):
        raise invalid("VALIDATION_ERROR", "지정한 열이 파일에 없습니다.")
    if len(set(chosen)) != len(chosen):
        raise invalid("VALIDATION_ERROR", "열은 서로 달라야 합니다.")
    if opts.quantity_col is not None and opts.date_col is None:
        raise invalid("VALIDATION_ERROR", "수량 열을 고르면 입고일 열도 골라야 합니다.")


def _check_one_supplier(rows: list[list[str]], result: dict, opts: ReceiptImportOptions) -> None:
    """공급업체 열을 골랐다면 새 품목 행의 업체가 한 곳인지 본다. 섞였으면 422 로 나눠 올리게 한다.

    기본 공급업체는 파일 하나에 하나만 고르므로, 섞인 파일을 그대로 받으면 다른 업체 품목까지 같은 업체로 등록된다.
    업체 이름으로 공급업체를 찾아 연결하지는 않는다 (열은 섞임 확인용).
    """
    if opts.supplier_col is None:
        return
    names = sorted({_get(rows[p["row"] - 2], opts.supplier_col) for p in result["new_products"]} - {""})
    if len(names) > 1:
        shown = ", ".join(names[:5]) + (" 등" if len(names) > 5 else "")
        raise AppError(422, "MULTIPLE_SUPPLIERS",
                       f"새 품목의 공급업체가 {len(names)}곳({shown}) 섞여 있습니다. 공급업체별로 파일을 나눠 올려 주세요.",
                       {"suppliers": names[:20]})


def preview(company_id: int, db: Session, filename: str, content: bytes, opts: ReceiptImportOptions) -> dict:
    """2단계: 미리보기. 아무것도 쓰지 않는다. 고른 공급업체가 다른 회사·비활성이면 여기서 바로 알린다."""
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    if opts.default_supplier_id is not None:
        check_default_supplier(company_id, db, opts.default_supplier_id)
    result = analyze(company_id, db, rows, opts, seoul_today())
    _check_one_supplier(rows, result, opts)
    return summarize(result, len(rows))


def commit(company_id: int, db: Session, user_id: int, filename: str, content: bytes, opts: ReceiptImportOptions) -> dict:
    """3단계: 반영. 새 품목 등록과 입고를 한 트랜잭션으로 (commit 은 API 가 한 번만 한다).

    미리보기를 믿지 않고 잠근 뒤 다시 계산한다. 잠금 순서는 판매 가져오기와 같은 "품목 번호 오름차순".
    """
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    skus = {_get(r, opts.product_col).upper() for r in rows} - {""}
    if skus:  # ① 파일에 나온 기존 품목을 번호순으로 먼저 잠근다 (register_movement 가 날짜순으로 잠그면 두 요청이 엇갈려 멈출 수 있다)
        db.execute(
            select(Product.id).where(Product.company_id == company_id, Product.sku.in_(skus))
            .order_by(Product.id).with_for_update()
        ).all()
    result = analyze(company_id, db, rows, opts, seoul_today())  # ② 잠근 뒤 다시 계산
    _check_one_supplier(rows, result, opts)
    if result["problems"] and not opts.exclude_problems:
        raise AppError(409, "IMPORT_HAS_PROBLEMS", f"문제 행이 {len(result['problems'])}건 있어 반영할 수 없습니다.",
                       {"problem_count": len(result["problems"])})
    if not result["to_apply"] and not result["new_products"]:
        raise AppError(409, "NOTHING_TO_IMPORT", "반영할 행이 없습니다.")
    if result["new_products"]:
        if opts.default_supplier_id is None:
            raise AppError(422, "VALIDATION_ERROR", "새 품목의 기본 공급업체를 골라 주세요.",
                           [{"field": "default_supplier_id", "reason": "required"}])
        check_default_supplier(company_id, db, opts.default_supplier_id)  # 다른 회사 404, 비활성 409
    try:
        # ③ 새 품목을 먼저 만든다 (회사는 토큰에서, 기본 공급업체는 올릴 때 고른 하나)
        db.add_all(Product(company_id=company_id, default_supplier_id=opts.default_supplier_id,
                           **{k: v for k, v in p.items() if k != "row"}) for p in result["new_products"])
        db.flush()  # 같은 SKU 가 동시에 만들어지면 여기서 유일 제한에 걸린다
        ids = dict(db.execute(  # SKU → 품목 번호 (방금 만든 품목 포함)
            select(Product.sku, Product.id).where(Product.company_id == company_id, Product.sku.in_({c.sku for c in result["to_apply"]}))
        ).all()) if result["to_apply"] else {}
        # ④ 날짜순으로 입고를 쓴다 (발주 없는 직접 입고)
        for c in result["to_apply"]:
            stock_service.register_movement(
                company_id, db, user_id, product_id=ids[c.sku], movement_type="RECEIPT", direction="IN",
                quantity=c.quantity, movement_date=c.day, external_ref=c.ref,
            )
    except IntegrityError:  # 같은 파일·같은 새 SKU 가 동시에 반영된 드문 경우: DB 유일 제한이 막는다
        raise AppError(409, "IMPORT_CONFLICT", "같은 품목이나 입고가 동시에 반영되었습니다. 미리보기부터 다시 하세요.") from None
    return {
        "created_product_count": len(result["new_products"]),
        "imported_count": len(result["to_apply"]),
        "total_quantity": result["total_quantity"],
        "date_from": result["date_from"],
        "date_to": result["date_to"],
        "skipped_count": sum(result["skipped"].values()),
        "problem_count": len(result["problems"]),
    }
