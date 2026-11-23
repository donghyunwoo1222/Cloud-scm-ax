"""안내 챗봇 경로 (#199). 관리자·담당자 모두 쓴다. 회사·사용자는 로그인 토큰에서만 가져온다."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자
from app.db import DB  # 요청마다 DB 세션
from app.schemas.chat import ChatGuideRequest  # 질문 모양 (길이·개수 한도)
from app.services import chat_guide  # 안내서·한도·LLM 호출

router = APIRouter(prefix="/chat/guide")  # 이 파일의 경로는 모두 /chat/guide 로 시작


@router.post("")  # 질문 하나에 답 하나 (LLM 을 부르므로 POST). 질문·답 글은 저장하지 않는다
def ask(body: ChatGuideRequest, user: CurrentUser, db: DB) -> dict:
    history = [turn.model_dump() for turn in body.history]
    return {"data": chat_guide.ask_guide(db, user.company_id, user.id, body.question, history)}


@router.get("/toc")  # 안내서 목차 (읽기만, LLM 안 부름, 스위치가 꺼져도 응답)
def toc(user: CurrentUser) -> dict:
    return {"data": chat_guide.toc()}
