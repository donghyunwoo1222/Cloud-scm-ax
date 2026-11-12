"""품목 관리 (F3). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1)."""

from sqlalchemy import Select, or_  # 조회문 타입과 조건 중 하나라도 맞는 비교
from sqlalchemy.exc import IntegrityError  # 제약 위반 오류
from sqlalchemy.orm import Session  # DB 세션 타입

from app.errors import AppError  # 공통 오류
from app.models import Product, Supplier  # 품목, 공급업체 표
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.products import ProductCreate, ProductUpdate  # 요청 모양
from app.services.tenant import check_ref, get_owned, scoped  # 회사 분리 도우미 (#23)


def filter_product_search(stmt: Select, q: str | None, group_code: str | None = None) -> Select:  # 품목 목록·재고 목록·추천 목록이 쓰는 같은 검색 조건
    code = group_code.strip().upper() if group_code else ""  # 그룹 코드는 대문자로 저장하므로 대문자로 맞춰 비교한다
    if code:  # 그룹 코드를 골랐으면
        stmt = stmt.where(Product.group_code == code)  # 정확히 같은 그룹만 남긴다 (예: TS-BASIC 은 TS-BASIC-2 와 다르다)
    term = q.strip() if q else ""  # 앞뒤 공백을 빼고, 검색어가 없으면 빈 문자열로 본다
    if not term:  # 비었거나 공백만 있으면
        return stmt  # 지금까지의 조건 그대로 돌려준다
    return stmt.where(or_(  # SKU·품목명·그룹 코드·옵션 중 한 곳에 검색어가 들어 있으면 선택한다
        Product.group_code.icontains(term, autoescape=True),  # 그룹 코드에서도 찾는다
        Product.color.icontains(term, autoescape=True),  # 색상 (예: "검정")
        Product.size.icontains(term, autoescape=True),  # 사이즈 (예: "M")
        Product.spec.icontains(term, autoescape=True),  # 규격 (예: "2L")
        Product.sku.icontains(term, autoescape=True),  # SKU에서 대소문자 없이 찾고 %·_는 글자 그대로 읽는다
        Product.name.icontains(term, autoescape=True),  # 품목명에도 같은 규칙을 적용한다
    ))


def list_products(
    company_id: int, db: Session, page: PageParams, include_inactive: bool, q: str | None,
    *, default_supplier_id: int | None = None,  # 기본 공급업체를 지정한 호출만 필터를 적용한다
    group_code: str | None = None,  # 그룹 코드를 지정한 호출만 정확 일치 필터를 적용한다
) -> tuple[list, dict]:
    """우리 회사 품목 목록. 최신순, 기본은 활성만, q 는 SKU·품목명·그룹 코드·옵션 부분 일치(대소문자 무시)."""
    stmt = scoped(company_id, Product)  # 회사 조건이 붙은 시작점
    if default_supplier_id is not None:  # 공급업체가 선택됐으면
        stmt = stmt.where(Product.default_supplier_id == default_supplier_id)  # 쪽을 자르기 전에 업체에 속한 품목만 남긴다
    if not include_inactive:  # 비활성 포함을 요청하지 않았으면
        stmt = stmt.where(Product.is_active.is_(True))  # 활성만
    stmt = filter_product_search(stmt, q, group_code)  # 쪽을 나누기 전에 기존 품목 검색 조건을 적용한다
    stmt = stmt.order_by(Product.created_at.desc(), Product.id.desc())  # 최신순
    return paginate(db, stmt, page)  # 한 쪽 + meta


def suppliers_of(company_id: int, db: Session, products: list[Product]) -> dict[int, Supplier]:
    """품목들의 기본 공급업체를 한 번의 조회로 가져온다 (품목마다 따로 묻지 않도록)."""
    ids = {p.default_supplier_id for p in products}  # 필요한 공급업체 id 모음
    rows = db.scalars(scoped(company_id, Supplier).where(Supplier.id.in_(ids))) if ids else []  # 한 번에 조회
    return {s.id: s for s in rows}  # id → 공급업체


def products_by_ids(company_id: int, db: Session, ids: set[int]) -> list[Product]:
    """같은 회사 품목들을 한 번의 조회로 가져온다 (이력 목록의 품목명·SKU 용)."""
    return list(db.scalars(scoped(company_id, Product).where(Product.id.in_(ids)))) if ids else []  # 빈 집합이면 조회 생략


def get_product(company_id: int, db: Session, product_id: int) -> Product:
    return get_owned(company_id, db, Product, product_id)  # 다른 회사·없는 id 는 404


def create_product(company_id: int, db: Session, data: ProductCreate) -> Product:
    """품목 등록. 기본 공급업체는 같은 회사의 활성 업체만."""
    check_box_settings(data.units_per_box, data.box_unit_cost)
    check_default_supplier(company_id, db, data.default_supplier_id)  # 다른 회사 404, 비활성 409
    values = data.model_dump()  # 요청 칸
    values["order_unit"] = order_unit_for(data.units_per_box, data.order_unit, sent=data.order_unit is not None)
    product = Product(company_id=company_id, **values)  # 요청 칸 + 회사 (회사는 토큰에서)
    db.add(product)  # 세션에 올림
    commit_product(db)  # 확정, 같은 SKU 면 409
    return product


def update_product(company_id: int, db: Session, product_id: int, data: ProductUpdate) -> Product:
    """수정·비활성·다시 활성. 보낸 칸만 바꾼다. 기본 공급업체를 바꿀 때만 그 업체를 검사한다."""
    product = get_owned(company_id, db, Product, product_id, lock=True)  # 두 박스 설정을 같은 시점에서 검사한다
    changes = data.model_dump(exclude_unset=True)  # 요청에 들어 있던 칸만
    check_box_settings(
        changes.get("units_per_box", product.units_per_box),
        changes.get("box_unit_cost", product.box_unit_cost),
    )
    if "default_supplier_id" in changes:  # 기본 공급업체를 바꾸면
        check_default_supplier(company_id, db, changes["default_supplier_id"])  # 새 업체를 검사
    units_per_box = changes.get("units_per_box", product.units_per_box)  # 저장 뒤의 박스 입수
    sent = changes.get("order_unit") is not None  # 이번 요청이 발주단위 이름을 보냈는지
    changes["order_unit"] = order_unit_for(units_per_box, changes.get("order_unit", product.order_unit), sent=sent)
    for field, value in changes.items():
        setattr(product, field, value)  # 값을 바꾼다
    commit_product(db)  # 확정, SKU 를 바꿔 겹치면 409
    return product


def check_box_settings(units_per_box: int | None, box_unit_cost: int | None) -> None:
    if (units_per_box is None) != (box_unit_cost is None):  # 두 값이 있어야 박스 수량과 금액을 모두 계산할 수 있다
        raise AppError(422, "VALIDATION_ERROR", "박스 입수와 박스당 구매 단가는 함께 설정하거나 해제하세요.")


def order_unit_for(units_per_box: int | None, order_unit: str | None, *, sent: bool) -> str | None:
    """저장할 발주단위 이름. 박스 설정이 없으면 None, 있으면 보낸 값 또는 "박스".

    예) 입수 10 + 이름 없음 → "박스", 입수 10 + "PACK" → "PACK", 입수 없음 + "PACK" → 422, 입수 해제 → None.
    """
    if units_per_box is None:  # 박스 설정이 없는 품목은 재고 단위로만 발주한다
        if sent:  # 환산계수 없이 이름만 보내면 몇 개인지 알 수 없다
            raise AppError(422, "VALIDATION_ERROR", "발주단위는 박스 입수와 박스당 구매 단가를 함께 설정할 때만 정할 수 있습니다.",
                           [{"field": "order_unit", "reason": "requires_box_settings"}])
        return None  # 박스 설정을 해제하면 이름도 함께 비운다
    return order_unit or "박스"  # 이름을 비우면 기존 화면과 같은 "박스"


def check_default_supplier(company_id: int, db: Session, supplier_id: int) -> Supplier:
    """기본 공급업체 검사: 같은 회사가 아니면 404(check_ref), 비활성이면 409 INACTIVE_REFERENCE."""
    supplier = check_ref(company_id, db, Supplier, supplier_id, "default_supplier_id")  # 다른 회사·없는 id 는 404
    if not supplier.is_active:  # 비활성 업체는 새로 고를 수 없다 (이미 연결된 품목은 그대로 둔다)
        raise AppError(
            409, "INACTIVE_REFERENCE", "비활성 공급업체는 기본 공급업체로 고를 수 없습니다.",
            [{"field": "default_supplier_id", "reason": "inactive"}],
        )
    return supplier


def commit_product(db: Session) -> None:
    """확정. 같은 회사에 같은 SKU 가 있으면(uq_products_company_sku) 되돌리고 409 DUPLICATE_SKU."""
    try:
        db.commit()  # 확정
    except IntegrityError as e:  # 제약 위반이면
        db.rollback()  # 이번 변경 취소
        if getattr(e.orig.diag, "constraint_name", None) == "uq_products_company_sku":  # 회사 안 SKU 유일 제약이면
            raise AppError(
                409, "DUPLICATE_SKU", "이미 같은 SKU 의 품목이 있습니다.", [{"field": "sku", "reason": "duplicate"}]
            ) from None
        raise  # 그 밖의 위반은 예상 밖이라 그대로 올린다 (500)
