"""품목 마스터 가져오기 (#189): 엑셀·CSV 로 품목을 새로 등록하거나 기존 품목을 고친다.

판매(#154)·입고(#155) 가져오기와 같은 틀이다: 서버는 파일을 저장하지 않고 열 확인 → 미리보기 → 반영마다 파일을 다시 받는다.
- 마스터 정보만 다룬다. 재고 이동은 만들지 않는다 (기초 재고는 #155 입고 가져오기로 넣는다).
- SKU(공백 제거·대문자)로 우리 회사 품목과 맞춘다. 있으면 수정, 없으면 신규.
- 빈 칸은 "변경 없음"이다 (값을 비우는 기능은 없다). is_active 와 기본 공급업체는 기존 품목에서 건드리지 않는다.
"""

from pydantic import ValidationError  # 행 값 검사 실패
from sqlalchemy import select  # SELECT 문
from sqlalchemy.exc import IntegrityError  # DB 유일 제한 위반
from sqlalchemy.orm import Session  # DB 세션

from app.errors import AppError  # 공통 오류
from app.models import Product  # 품목
from app.schemas.product_import import ProductImportOptions, ProductRow  # 열 지정, 행 값 규칙
from app.services.products import (  # 품목 등록·수정과 같은 규칙
    check_box_settings,
    check_default_supplier,
    order_unit_for,
)
from app.services.receipt_import import _int_or_text  # 정수 글자 → 정수 (쉼표 허용)
from app.services.sales_import import (  # 파일 읽기·열 힌트를 그대로 쓴다
    MAX_PROBLEMS_SHOWN,
    _get,
    invalid,
    read_table,
    suggest_columns,
)

HINTS = {  # 열 미리 선택 힌트 (일반 낱말만)
    "product_col": ["sku", "품목코드", "상품코드"],
    "name_col": ["품목명", "상품명", "품명", "name"],
    "unit_col": ["기본단위", "재고단위"],
    "cost_col": ["구매단가", "매입가", "원가"],
    "safety_col": ["안전재고", "safety"],
    "order_unit_col": ["발주단위 이름", "발주단위명"],
    "factor_col": ["환산계수", "입수"],
    "box_cost_col": ["발주단위 단가", "발주단위단가"],
    "moq_col": ["최소 주문량", "최소주문량", "moq"],
    "color_col": ["색상", "color"],
    "size_col": ["사이즈", "size"],
    "spec_col": ["규격", "spec"],
    "group_col": ["그룹 코드", "그룹코드", "group"],
}

# 응답·메시지에 쓰는 칸 이름: 품목 칸 → (옵션의 열 이름, 화면에 보일 이름)
FIELDS = {
    "name": ("name_col", "품목명"),
    "unit": ("unit_col", "기본단위"),
    "unit_cost": ("cost_col", "구매단가"),
    "safety_stock": ("safety_col", "안전재고"),
    "order_unit": ("order_unit_col", "발주단위 이름"),
    "units_per_box": ("factor_col", "환산계수"),
    "box_unit_cost": ("box_cost_col", "발주단위 단가"),
    "min_order_units": ("moq_col", "최소 주문량"),
    "color": ("color_col", "색상"),
    "size": ("size_col", "사이즈"),
    "spec": ("spec_col", "규격"),
    "group_code": ("group_col", "그룹 코드"),
}
INT_FIELDS = {"unit_cost", "safety_stock", "units_per_box", "box_unit_cost", "min_order_units"}  # 정수로 읽는 칸
NEW_REQUIRED = ("name", "unit", "unit_cost")  # 신규 품목에 값이 꼭 있어야 하는 칸

PROBLEM_MESSAGES = {
    "MISSING_SKU": "SKU 가 비어 있거나 50자를 넘습니다.",
    "DUPLICATE_SKU_IN_FILE": "파일 안에서 SKU 가 앞의 행과 겹칩니다.",
    "BOX_SETTINGS_INCOMPLETE": "환산계수와 발주단위 단가는 함께 있어야 하고, 발주단위 이름은 환산계수가 있을 때만 쓸 수 있습니다.",
}


def inspect_file(filename: str, content: bytes) -> dict:
    """1단계: 머리글·행 수·열 미리 선택 힌트 (값은 돌려주지 않는다)."""
    headers, rows = read_table(filename, content)
    return {"headers": headers, "row_count": len(rows), "suggested": suggest_columns(headers, HINTS)}


def _read_values(row: list[str], opts: ProductImportOptions) -> tuple[dict | None, list[str]]:
    """행 → (검사를 통과한 값들, 틀린 칸 이름들). 빈 칸은 값 목록에 넣지 않는다 (= 변경 없음)."""
    raw = {}
    for field, (col_name, _label) in FIELDS.items():
        col = getattr(opts, col_name)
        text = _get(row, col) if col is not None else ""
        if text:
            raw[field] = _int_or_text(text) if field in INT_FIELDS else text  # 정수가 아닌 글자는 그대로 둬서 검사에서 걸린다 (예: 1.5, -1)
    try:
        return ProductRow(**raw).model_dump(exclude_none=True), []
    except ValidationError as e:
        return None, sorted({FIELDS[str(err["loc"][0])][1] for err in e.errors()})


def _final_order_unit(values: dict, product: Product | None) -> str | None:
    """파일 값과 기존 값을 합친 최종 발주단위 이름. 박스 설정 규칙을 어기면 AppError.

    예) 기존 환산계수 12·단가 13000, 파일에 환산계수 24만 → 합치면 24·13000 이라 허용.
        기존 박스 설정 없음, 파일에 환산계수만 → 단가가 없어 문제.
    """
    upb = values.get("units_per_box", product.units_per_box if product else None)
    cost = values.get("box_unit_cost", product.box_unit_cost if product else None)
    check_box_settings(upb, cost)
    return order_unit_for(upb, values.get("order_unit", product.order_unit if product else None), sent="order_unit" in values)


def analyze(company_id: int, db: Session, rows: list[list[str]], opts: ProductImportOptions) -> dict:
    """행들을 검사해 신규·수정·변경 없음·문제를 가른다. DB 는 읽기만 한다.

    판단 순서(행 하나당 첫 사유 하나): SKU 비었음 → 파일 안 SKU 중복 → 칸 값 검사 → (신규) 필수 칸 → 박스 설정 규칙
    """
    skus = {_get(r, opts.product_col).upper() for r in rows} - {""}
    existing = {p.sku: p for p in db.scalars(  # 우리 회사 품목만 (다른 회사 SKU 는 없는 것으로 보여 신규가 된다)
        select(Product).where(Product.company_id == company_id, Product.sku.in_(skus))
    )} if skus else {}
    problems: list[dict] = []
    new_products: list[dict] = []
    updates: list[dict] = []
    unchanged = 0
    seen: set[str] = set()

    def problem(row_no: int, reason: str, message: str | None = None, sku: str | None = None) -> None:
        problems.append({"row": row_no, "reason": reason, "message": message or PROBLEM_MESSAGES[reason], "sku": sku})

    for offset, row in enumerate(rows):
        row_no = offset + 2  # 머리글 1, 첫 데이터 2 (엑셀과 같은 번호)
        sku = _get(row, opts.product_col).upper()
        if not sku or len(sku) > 50:
            problem(row_no, "MISSING_SKU")
            continue
        if sku in seen:
            problem(row_no, "DUPLICATE_SKU_IN_FILE", sku=sku)  # 앞 행은 유지하고 뒤의 겹친 행만 막는다
            continue
        seen.add(sku)
        values, bad = _read_values(row, opts)
        if values is None:
            problem(row_no, "INVALID_VALUE", f"{', '.join(bad)} 값이 올바르지 않습니다.", sku)
            continue
        product = existing.get(sku)
        if product is None and (missing := [FIELDS[f][1] for f in NEW_REQUIRED if f not in values]):
            problem(row_no, "MISSING_REQUIRED", f"새 품목은 {', '.join(missing)}이(가) 꼭 있어야 합니다.", sku)
            continue
        try:
            order_unit = _final_order_unit(values, product)
        except AppError:
            problem(row_no, "BOX_SETTINGS_INCOMPLETE", sku=sku)
            continue
        if product is None:
            new_products.append({
                "row": row_no, "sku": sku, "safety_stock": 0, "units_per_box": None, "box_unit_cost": None,
                "min_order_units": None, "color": None, "size": None, "spec": None, "group_code": None,
                **values, "order_unit": order_unit,
            })
            continue
        changes = {f: v for f, v in values.items() if f != "order_unit" and getattr(product, f) != v}
        if order_unit != product.order_unit:  # 환산계수만 새로 넣으면 이름이 "박스"로 채워진다
            changes["order_unit"] = order_unit
        if changes:
            updates.append({"row": row_no, "sku": sku, "product": product, "changes": changes})
        else:
            unchanged += 1
    return {"new_products": new_products, "updates": updates, "unchanged": unchanged, "problems": problems}


def summarize(result: dict, total_rows: int) -> dict:
    """analyze 결과 → 응답용 요약 (목록은 200개까지만 담는다)."""
    updates = [
        {"row": u["row"], "sku": u["sku"], "name": u["product"].name,
         "changes": [{"field": f, "label": FIELDS[f][1], "old": getattr(u["product"], f), "new": v} for f, v in u["changes"].items()]}
        for u in result["updates"][:MAX_PROBLEMS_SHOWN]
    ]
    return {
        "total_rows": total_rows,
        "new_count": len(result["new_products"]),
        "update_count": len(result["updates"]),
        "unchanged_count": result["unchanged"],
        "new_products": result["new_products"][:MAX_PROBLEMS_SHOWN],
        "updates": updates,
        "problem_count": len(result["problems"]),
        "problems": result["problems"][:MAX_PROBLEMS_SHOWN],
    }


def _check_columns(headers: list[str], opts: ProductImportOptions) -> None:
    """지정한 열이 파일 안에 있는지, 서로 겹치지 않는지 검사 (어기면 422)."""
    chosen = [opts.product_col] + [getattr(opts, col) for col, _ in FIELDS.values() if getattr(opts, col) is not None]
    if any(c >= len(headers) for c in chosen):
        raise invalid("VALIDATION_ERROR", "지정한 열이 파일에 없습니다.")
    if len(set(chosen)) != len(chosen):
        raise invalid("VALIDATION_ERROR", "열은 서로 달라야 합니다.")


def preview(company_id: int, db: Session, filename: str, content: bytes, opts: ProductImportOptions) -> dict:
    """2단계: 미리보기. 아무것도 쓰지 않는다. 고른 공급업체가 다른 회사·비활성이면 여기서 바로 알린다."""
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    if opts.default_supplier_id is not None:
        check_default_supplier(company_id, db, opts.default_supplier_id)
    return summarize(analyze(company_id, db, rows, opts), len(rows))


def commit(company_id: int, db: Session, filename: str, content: bytes, opts: ProductImportOptions) -> dict:
    """3단계: 반영. 신규 등록과 수정을 한 트랜잭션으로 (commit 은 API 가 한 번만 한다).

    미리보기를 믿지 않고 품목을 번호순으로 잠근 뒤 다시 계산한다. 그 사이 다른 사용자가 같은 SKU 를 먼저 등록했다면
    그 행은 신규가 아니라 수정(또는 변경 없음)으로 처리된다. 화면이 보낸 expected_* 와 다르면 응답의 preview_changed 로 알린다.
    """
    headers, rows = read_table(filename, content)
    _check_columns(headers, opts)
    skus = {_get(r, opts.product_col).upper() for r in rows} - {""}
    if skus:  # ① 파일에 나온 기존 품목을 번호순으로 먼저 잠근다 (두 요청이 서로 반대 순서로 잠가 멈추는 일을 막는다)
        db.execute(
            select(Product.id).where(Product.company_id == company_id, Product.sku.in_(skus))
            .order_by(Product.id).with_for_update()
        ).all()
    result = analyze(company_id, db, rows, opts)  # ② 잠근 뒤 다시 계산
    if result["problems"] and not opts.exclude_problems:
        raise AppError(409, "IMPORT_HAS_PROBLEMS", f"문제 행이 {len(result['problems'])}건 있어 반영할 수 없습니다.",
                       {"problem_count": len(result["problems"])})
    if not result["new_products"] and not result["updates"]:
        raise AppError(409, "NOTHING_TO_IMPORT", "반영할 행이 없습니다.")
    if result["new_products"]:
        if opts.default_supplier_id is None:
            raise AppError(422, "VALIDATION_ERROR", "새 품목의 기본 공급업체를 골라 주세요.",
                           [{"field": "default_supplier_id", "reason": "required"}])
        check_default_supplier(company_id, db, opts.default_supplier_id)  # 다른 회사 404, 비활성 409
    try:
        db.add_all(Product(company_id=company_id, default_supplier_id=opts.default_supplier_id,
                           **{k: v for k, v in p.items() if k != "row"}) for p in result["new_products"])  # 회사는 토큰에서
        for u in result["updates"]:  # 기존 품목: 파일에 값이 있던 칸만 바꾼다 (활성 여부·기본 공급업체는 그대로)
            for field, value in u["changes"].items():
                setattr(u["product"], field, value)
        db.flush()  # 같은 SKU 가 동시에 만들어지면 여기서 유일 제한에 걸린다
    except IntegrityError:
        raise AppError(409, "IMPORT_CONFLICT", "같은 품목이 동시에 반영되었습니다. 미리보기부터 다시 하세요.") from None
    created, updated = len(result["new_products"]), len(result["updates"])
    exp_new = created if opts.expected_new_count is None else opts.expected_new_count  # 안 보낸 쪽은 비교하지 않는다
    exp_update = updated if opts.expected_update_count is None else opts.expected_update_count
    changed = (exp_new, exp_update) != (created, updated)
    return {
        "created_count": created,
        "updated_count": updated,
        "unchanged_count": result["unchanged"],
        "problem_count": len(result["problems"]),
        "preview_changed": changed,  # 미리보기와 건수가 달라졌는지 (달라도 반영은 끝난 상태)
        "message": (f"미리보기와 달라졌습니다. 신규 {exp_new}→{created}건, 수정 {exp_update}→{updated}건으로 반영했습니다."
                    if changed else None),
    }

