"""재고 조회 경로 (F5). 관리자·담당자 모두 사용. 읽기만 한다."""

from typing import Annotated  # 타입에 부가 정보를 붙이는 도구

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.clock import seoul_today  # 서울 기준 오늘 (추천 계산 기준일)
from app.db import DB  # 요청마다 DB 세션
from app.pagination import Page  # page·page_size
from app.schemas.common import PathId  # 번호 칸 (DB 범위를 넘으면 422, #71)
from app.schemas.stock import Status, StockOut  # 상태 값, 응답 모양
from app.services import inventory_status  # 현재고 + 부족/정상/판단 불가 (#76)

router = APIRouter(prefix="/stock")  # 이 파일의 경로는 모두 /stock 으로 시작


@router.get("")  # 품목별 현재고 목록
def list_stock(
    user: CurrentUser,
    db: DB,
    page: Page,
    include_inactive: Annotated[bool, Query()] = False,  # true 면 비활성 품목 포함 (기본은 숨김)
    status: Annotated[Status | None, Query()] = None,  # 상태로 거르기 (SHORTAGE·NORMAL·UNKNOWN, 그 밖은 422)
) -> dict:
    rows, meta = inventory_status.list_stock(user.company_id, db, seoul_today(), page, include_inactive, status)  # 회사는 토큰 사용자에게서
    return {"data": [StockOut(**r).model_dump(mode="json") for r in rows], "meta": meta}


@router.get("/{product_id}")  # 품목 하나의 현재고
def get_stock(product_id: PathId, user: CurrentUser, db: DB) -> dict:
    return {"data": StockOut(**inventory_status.get_stock(user.company_id, db, seoul_today(), product_id)).model_dump(mode="json")}  # 다른 회사 404
