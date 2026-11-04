"""발주 추천 경로 (F8). 관리자·담당자 모두 사용. 읽기만 하므로 commit 하지 않는다."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.clock import seoul_today  # 서울 기준 오늘
from app.db import DB  # 요청마다 DB 세션
from app.services import recommendations as recommendation_service  # 추천 조회

router = APIRouter(prefix="/recommendations")  # 이 파일의 경로는 모두 /recommendations 로 시작


@router.get("")  # 추천 목록 (요청이 올 때 계산, 저장하지 않음)
def list_recommendations(user: CurrentUser, db: DB) -> dict:
    return {"data": recommendation_service.list_recommendations(user.company_id, db, seoul_today())}  # 회사는 토큰에서, 오늘은 서울 기준 한 번
