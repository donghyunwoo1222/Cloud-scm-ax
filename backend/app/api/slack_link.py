"""슬랙 연결 경로 (#197). 관리자·담당자 모두 자기 연결만 다룬다. 회사·사용자는 로그인 토큰에서만 가져온다."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자
from app.db import DB  # 요청마다 DB 세션
from app.services import slack_link  # 연결 코드 발급·해제

router = APIRouter(prefix="/slack/link")  # 이 파일의 경로는 모두 /slack/link 로 시작


@router.get("")  # 내 연결 상태 (읽기만)
def get_status(user: CurrentUser, db: DB) -> dict:
    return {"data": slack_link.status(db, user)}


@router.post("/code", status_code=201)  # 새 연결 코드 (원문은 이 응답에만 한 번 나간다)
def issue_code(user: CurrentUser, db: DB) -> dict:
    code, expires_at = slack_link.issue_code(db, user, slack_link.now())  # 꺼져 있으면 503, 이미 연결이면 409
    return {"data": {"code": code, "expires_at": expires_at}}


@router.post("/unlink")  # 연결 해제 (상태 변경은 POST, 슬랙이 꺼져 있어도 된다)
def unlink(user: CurrentUser, db: DB) -> dict:
    slack_link.unlink(db, user)
    return {"data": slack_link.status(db, user)}
