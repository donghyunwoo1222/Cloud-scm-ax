"""판매 분석 경로 (#357). 관리자·담당자 모두 사용(재고 조회와 같은 권한). 읽기만 한다."""

from typing import Annotated, Literal  # 정해진 값 중 하나

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.clock import seoul_today  # 서울 기준 오늘
from app.db import ReadDB  # 한 시점으로 읽는 조회 세션 (여러 집계를 같은 시점에서)
from app.services import sales_analytics  # 판매 집계

router = APIRouter(prefix="/sales-analytics")


@router.get("")  # 기간 판매 추이·품목별 판매·소진 예상일 한 번에
def get_sales_analytics(
    user: CurrentUser,
    db: ReadDB,
    days: Annotated[Literal["7", "30", "90"], Query()] = "30",  # 기간(일), 그 밖은 422 (쿼리 문자열이라 문자로 받는다)
    bucket: Annotated[Literal["day", "week"], Query()] = "day",  # 추이 단위
) -> dict:
    return {"data": sales_analytics.get_sales_analytics(user.company_id, db, seoul_today(), int(days), bucket)}  # 회사는 토큰에서
