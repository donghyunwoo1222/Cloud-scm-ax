"""품목 경로. 관리자·담당자 모두 사용(CurrentUser). 삭제 경로는 없다(비활성으로 대신)."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.models import Product, Supplier  # 품목, 공급업체 표
from app.pagination import Page  # page·page_size
from app.schemas.common import PathId, QueryId  # 경로·목록의 번호 칸 (DB 범위를 넘으면 422)
from app.schemas.products import (  # 요청·응답 모양
    ProductCreate,
    ProductOut,
    ProductUpdate,
    SupplierBrief,
)
from app.services import products as products_service  # 업무 규칙

router = APIRouter(prefix="/products")  # 이 파일의 경로는 모두 /products 로 시작


def out(product: Product, supplier: Supplier) -> dict:
    """품목 + 기본 공급업체 요약 → 응답 모양 (재고 숫자는 없음)."""
    return ProductOut(
        id=product.id, sku=product.sku, name=product.name, unit=product.unit,
        color=product.color, size=product.size, spec=product.spec, group_code=product.group_code,
        unit_cost=product.unit_cost, safety_stock=product.safety_stock, is_active=product.is_active,
        units_per_box=product.units_per_box, box_unit_cost=product.box_unit_cost,
        order_unit=product.order_unit or product.unit, unit_factor=product.units_per_box or 1,  # 박스 설정이 없으면 재고 단위·1
        default_supplier=SupplierBrief.model_validate(supplier),  # id·이름·리드타임
        created_at=product.created_at, updated_at=product.updated_at,
    ).model_dump(mode="json")


def one(user, db, product: Product) -> dict:
    """품목 하나의 응답 {"data": ...}."""
    supplier = products_service.suppliers_of(user.company_id, db, [product])[product.default_supplier_id]  # 기본 공급업체
    return {"data": out(product, supplier)}


@router.get("")  # 목록
def list_products(
    user: CurrentUser,
    db: DB,
    page: Page,
    include_inactive: Annotated[bool, Query()] = False,  # true 면 비활성 포함 (기본은 숨김)
    q: Annotated[str | None, Query(max_length=100)] = None,  # SKU·품목명·그룹 코드·옵션 검색어
    default_supplier_id: QueryId = None,  # 선택한 기본 공급업체 번호
    group_code: Annotated[str | None, Query(max_length=50)] = None,  # 그룹 코드 정확 일치 (대소문자 무시)
) -> dict:
    rows, meta = products_service.list_products(
        user.company_id, db, page, include_inactive, q, default_supplier_id=default_supplier_id, group_code=group_code,  # 회사는 토큰에서, 업체는 필터에서 읽는다
    )
    suppliers = products_service.suppliers_of(user.company_id, db, rows)  # 기본 공급업체를 한 번에
    return {"data": [out(p, suppliers[p.default_supplier_id]) for p in rows], "meta": meta}


@router.post("", status_code=201)  # 등록
def create_product(data: ProductCreate, user: CurrentUser, db: DB) -> dict:
    return one(user, db, products_service.create_product(user.company_id, db, data))  # SKU 중복 409, 공급업체 404·409


@router.get("/{product_id}")  # 상세
def get_product(product_id: PathId, user: CurrentUser, db: DB) -> dict:
    return one(user, db, products_service.get_product(user.company_id, db, product_id))  # 다른 회사 404


@router.patch("/{product_id}")  # 수정·비활성·다시 활성
def update_product(product_id: PathId, data: ProductUpdate, user: CurrentUser, db: DB) -> dict:
    return one(user, db, products_service.update_product(user.company_id, db, product_id, data))  # 다른 회사 404
