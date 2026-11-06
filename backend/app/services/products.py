"""품목 관리 (F3). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1)."""

from sqlalchemy import Select, or_  # 조회문 타입과 조건 중 하나라도 맞는 비교
from sqlalchemy.exc import IntegrityError  # 제약 위반 오류
from sqlalchemy.orm import Session  # DB 세션 타입

from app.errors import AppError  # 공통 오류
from app.models import Product, Supplier  # 품목, 공급업체 표
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.products import ProductCreate, ProductUpdate  # 요청 모양
from app.services.tenant import check_ref, get_owned, scoped  # 회사 분리 도우미 (#23)


def filter_product_search(stmt: Select, q: str | None) -> Select:  # 품목 목록과 재고 목록에서 쓰는 같은 검색 조건
    term = q.strip() if q else ""  # 앞뒤 공백을 빼고, 검색어가 없으면 빈 문자열로 본다
    if not term:  # 비었거나 공백만 있으면
        return stmt  # 원래 조회 조건 그대로 돌려준다
    return stmt.where(or_(  # SKU와 품목명 중 한 곳에 검색어가 들어 있으면 선택한다
        Product.sku.icontains(term, autoescape=True),  # SKU에서 대소문자 없이 찾고 %·_는 글자 그대로 읽는다
        Product.name.icontains(term, autoescape=True),  # 품목명에도 같은 규칙을 적용한다
    ))


def list_products(
    company_id: int, db: Session, page: PageParams, include_inactive: bool, q: str | None,
    *, default_supplier_id: int | None = None,  # 기본 공급업체를 지정한 호출만 필터를 적용한다
) -> tuple[list, dict]:
    """우리 회사 품목 목록. 최신순, 기본은 활성만, q 는 SKU 또는 품목명 부분 일치(대소문자 무시)."""
    stmt = scoped(company_id, Product)  # 회사 조건이 붙은 시작점
    if default_supplier_id is not None:  # 공급업체가 선택됐으면
        stmt = stmt.where(Product.default_supplier_id == default_supplier_id)  # 쪽을 자르기 전에 업체에 속한 품목만 남긴다
    if not include_inactive:  # 비활성 포함을 요청하지 않았으면
        stmt = stmt.where(Product.is_active.is_(True))  # 활성만
    stmt = filter_product_search(stmt, q)  # 쪽을 나누기 전에 기존 품목 검색 조건을 적용한다
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
    product = Product(company_id=company_id, **data.model_dump())  # 요청 칸 + 회사 (회사는 토큰에서)
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
    for field, value in changes.items():
        setattr(product, field, value)  # 값을 바꾼다
    commit_product(db)  # 확정, SKU 를 바꿔 겹치면 409
    return product


def check_box_settings(units_per_box: int | None, box_unit_cost: int | None) -> None:
    if (units_per_box is None) != (box_unit_cost is None):  # 두 값이 있어야 박스 수량과 금액을 모두 계산할 수 있다
        raise AppError(422, "VALIDATION_ERROR", "박스 입수와 박스당 구매 단가는 함께 설정하거나 해제하세요.")


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
