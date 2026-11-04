"""회사 분리(R1) 공통 도우미. 모든 상세·수정·목록·참조 검사가 이 세 함수만 거친다."""

from sqlalchemy import Select, select  # SELECT 문 타입, 만들기
from sqlalchemy.orm import Session  # DB 세션 타입

from app.errors import AppError  # 공통 오류
from app.models.base import CompanyMixin  # company_id 칸을 가진 표들의 공통 부모

NOT_FOUND_MESSAGE = "대상을 찾을 수 없습니다."  # 없는 id든 다른 회사 id든 같은 문장 (있는지조차 알려주지 않는다)


def scoped[M: CompanyMixin](company_id: int, model: type[M]) -> Select[tuple[M]]:
    """목록 조회의 시작점: company_id 조건이 이미 붙은 SELECT. 여기에 필터·정렬만 더한다."""
    return select(model).where(model.company_id == company_id)  # 다른 회사 행은 처음부터 빠진다


def get_owned[M: CompanyMixin](company_id: int, db: Session, model: type[M], row_id: int, lock: bool = False) -> M:
    """경로의 id 로 행 하나 찾기. 같은 회사의 행만 찾고, 없거나 다른 회사면 404.

    lock=True 면 찾은 행을 트랜잭션이 끝날 때까지 잠근다(SELECT ... FOR UPDATE). 같은 행을 잠그려는 다른 요청은 기다린다.
    """
    stmt = scoped(company_id, model).where(model.id == row_id)  # 회사 조건 + id 조건을 함께
    row = db.scalar(stmt.with_for_update() if lock else stmt)  # 잠금이 필요하면 FOR UPDATE
    if row is None:  # 없는 id 와 다른 회사 id 가 여기서 똑같이 걸린다
        raise AppError(404, "NOT_FOUND", NOT_FOUND_MESSAGE)
    return row


def check_ref[M: CompanyMixin](
    company_id: int, db: Session, model: type[M], row_id: int, field: str, lock: bool = False
) -> M:
    """요청 본문이 가리키는 id 검사 (예: 품목의 default_supplier_id). 같은 회사 행이 아니면 404 + 어느 칸인지."""
    try:
        return get_owned(company_id, db, model, row_id, lock)  # 찾는 방법은 상세 조회와 같다
    except AppError as e:  # 못 찾았으면
        e.details = [{"field": field, "reason": "not_found"}]  # 어느 칸이 가리킨 행인지 알려준다
        raise
