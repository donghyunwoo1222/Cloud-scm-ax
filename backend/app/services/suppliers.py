"""공급업체 관리 (F2). 모든 함수는 company_id 를 첫 번째 인자로 받는다(R1)."""

from sqlalchemy.exc import IntegrityError  # 제약 위반 오류
from sqlalchemy.orm import Session  # DB 세션 타입

from app.errors import AppError  # 공통 오류
from app.models import Supplier  # 공급업체 표
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.schemas.suppliers import SupplierCreate, SupplierUpdate  # 요청 모양
from app.services.tenant import get_owned, scoped  # 회사 분리 도우미 (#23)


def list_suppliers(
    company_id: int, db: Session, page: PageParams, include_inactive: bool, q: str | None
) -> tuple[list, dict]:
    """우리 회사 공급업체 목록. 최신순, 기본은 활성만, q 는 업체명 부분 일치(대소문자 무시)."""
    stmt = scoped(company_id, Supplier)  # 회사 조건이 붙은 시작점
    if not include_inactive:  # 비활성 포함을 요청하지 않았으면
        stmt = stmt.where(Supplier.is_active.is_(True))  # 활성만
    if q and q.strip():  # 검색어가 있으면
        stmt = stmt.where(Supplier.name.icontains(q.strip(), autoescape=True))  # 예) "유통" → "다라유통"; %·_ 는 글자 그대로 찾는다
    stmt = stmt.order_by(Supplier.created_at.desc(), Supplier.id.desc())  # 최신순
    return paginate(db, stmt, page)  # 한 쪽 + meta


def get_supplier(company_id: int, db: Session, supplier_id: int) -> Supplier:
    return get_owned(company_id, db, Supplier, supplier_id)  # 다른 회사·없는 id 는 404


def create_supplier(company_id: int, db: Session, data: SupplierCreate) -> Supplier:
    """공급업체 등록. 회사는 토큰에서 온 값."""
    supplier = Supplier(company_id=company_id, **data.model_dump())  # 요청 칸 + 회사
    db.add(supplier)  # 세션에 올림
    commit_supplier(db)  # 확정, 같은 이름이면 409
    return supplier


def update_supplier(company_id: int, db: Session, supplier_id: int, data: SupplierUpdate) -> Supplier:
    """수정·비활성·다시 활성. 보낸 칸만 바꾼다."""
    supplier = get_owned(company_id, db, Supplier, supplier_id)  # 다른 회사·없는 id 는 404
    for field, value in data.model_dump(exclude_unset=True).items():  # 요청에 들어 있던 칸만
        setattr(supplier, field, value)  # 값을 바꾼다
    commit_supplier(db)  # 확정, 이름을 바꿔 겹치면 409
    return supplier


def commit_supplier(db: Session) -> None:
    """확정. 같은 회사에 같은 업체명이 있으면(uq_suppliers_company_name) 되돌리고 409 DUPLICATE_NAME."""
    try:
        db.commit()  # 확정
    except IntegrityError as e:  # 제약 위반이면
        db.rollback()  # 이번 변경 취소
        if getattr(e.orig.diag, "constraint_name", None) == "uq_suppliers_company_name":  # 회사 안 업체명 유일 제약이면
            raise AppError(
                409, "DUPLICATE_NAME", "이미 같은 이름의 공급업체가 있습니다.", [{"field": "name", "reason": "duplicate"}]
            ) from None
        raise  # 그 밖의 위반은 예상 밖이라 그대로 올린다 (500)
