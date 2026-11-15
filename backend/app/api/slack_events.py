"""슬랙 Events API 받는 문 (#197 PR 3, 배포용 HTTP 경로). 로그인 쿠키 대신 슬랙 서명이 유일한 열쇠다.

순서: 꺼져 있으면 404 → 원문 본문으로 서명 검증(실패 401) → url_verification 이면 challenge 반환
      → 그 밖에는 처리를 뒤 작업(BackgroundTasks)에 넣고 바로 200. 슬랙은 3초 안에 답이 없으면 다시 보낸다.
"""

import json  # 본문 해석 (서명 검증이 끝난 뒤에만)
import logging  # 서명 실패 한 줄

from fastapi import APIRouter, BackgroundTasks, Request  # 라우터, 응답 뒤 작업, 원문 본문

from app.config import settings  # SLACK_SIGNING_SECRET
from app.errors import AppError  # 공통 오류
from app.services import slack_events, slack_link  # 이벤트 처리, 스위치·시각

router = APIRouter(prefix="/slack")
log = logging.getLogger(__name__)


@router.post("/events")
async def receive_event(request: Request, background: BackgroundTasks) -> dict:
    if not slack_link.enabled() or not settings.slack_signing_secret.get_secret_value():
        raise AppError(404, "NOT_FOUND", "요청한 경로를 찾을 수 없습니다.")  # 꺼져 있으면 없는 경로처럼
    body = await request.body()  # 서명은 파싱 전 원문으로 계산한다
    if not slack_events.verify(body, request.headers):
        log.warning("slack_event outcome=BAD_SIGNATURE")
        raise AppError(401, "SLACK_BAD_SIGNATURE", "서명이 올바르지 않습니다.")
    try:
        envelope = json.loads(body)
    except ValueError:
        raise AppError(400, "BAD_REQUEST", "본문을 읽을 수 없습니다.") from None
    if not isinstance(envelope, dict):
        raise AppError(400, "BAD_REQUEST", "본문을 읽을 수 없습니다.")
    if envelope.get("type") == "url_verification":  # 슬랙 앱 설정에서 주소를 등록할 때 한 번
        return {"challenge": envelope.get("challenge")}
    background.add_task(slack_events.handle_event, envelope, slack_link.now())  # 응답(200)을 보낸 뒤 실행
    return {}
