"""목록 API 공통: page·page_size 받기, 쪽 자르기, meta 만들기. 모든 목록이 같은 모양을 쓴다."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import Depends, Query  # 의존성, 쿼리 문자열 칸
from pydantic import BaseModel  # 값 묶음
from sqlalchemy import Select, func, select  # SELECT 문, 개수 세기
from sqlalchemy.orm import Session  # DB 세션 타입


class PageParams(BaseModel):
    page: int  # 몇 번째 쪽 (1부터)
    page_size: int  # 한 쪽에 몇 개


def page_params(
    page: Annotated[int, Query(ge=1)] = 1,  # 1 미만이면 422
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,  # 기본 20개, 한 번에 100개까지만 (너무 큰 요청 방지)
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


Page = Annotated[PageParams, Depends(page_params)]  # 경로 함수에서 `page: Page` 로 받는다


def paginate(db: Session, stmt: Select, page: PageParams) -> tuple[list, dict]:
    """정렬까지 끝난 SELECT 를 한 쪽만 잘라 행 목록과 meta 를 돌려준다."""
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))  # 조건에 맞는 전체 개수
    rows = db.scalars(stmt.limit(page.page_size).offset((page.page - 1) * page.page_size)).all()  # 예) 2쪽, 20개씩 → 21~40번째
    return list(rows), {"page": page.page, "page_size": page.page_size, "total": total}  # meta: 쪽 번호, 쪽 크기, 전체 개수
