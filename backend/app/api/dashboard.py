"""대시보드 경로 (F7). 관리자·담당자 모두 사용. 읽기만 하므로 commit 하지 않는다."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.clock import seoul_today  # 서울 기준 오늘
from app.db import ReadDB  # 한 시점으로 읽는 조회 세션 (#84)
from app.services import dashboard as dashboard_service  # 대시보드 집계

router = APIRouter(prefix="/dashboard")  # 이 파일의 경로는 모두 /dashboard 로 시작


@router.get("")  # 요약 한 번에
def get_dashboard(user: CurrentUser, db: ReadDB) -> dict:  # 진행 중 발주·부족·과잉을 같은 시점에서 읽는다
    return {"data": dashboard_service.get_dashboard(user.company_id, db, seoul_today())}  # 회사는 토큰 사용자에게서, 오늘은 서울 기준
