"""재고 조회 경로 (F5). 관리자·담당자 모두 사용. 읽기만 한다."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.stock import StockOut  # 응답 모양
from app.services import stock as stock_service  # 재고 업무 규칙

router = APIRouter(prefix="/stock")  # 이 파일의 경로는 모두 /stock 으로 시작


@router.get("")  # 품목별 현재고 목록
def list_stock(
    user: CurrentUser,
    db: DB,
    page: Page,
    include_inactive: Annotated[bool, Query()] = False,  # true 면 비활성 품목 포함 (기본은 숨김)
) -> dict:
    rows, meta = stock_service.list_stock(user.company_id, db, page, include_inactive)  # 회사는 토큰 사용자에게서
    return {"data": [StockOut(**r).model_dump(mode="json") for r in rows], "meta": meta}


@router.get("/{product_id}")  # 품목 하나의 현재고
def get_stock(product_id: int, user: CurrentUser, db: DB) -> dict:
    return {"data": StockOut(**stock_service.get_stock(user.company_id, db, product_id)).model_dump(mode="json")}  # 다른 회사 404
