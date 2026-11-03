from fastapi import FastAPI  # FastAPI 앱 클래스

from app.api import auth, health  # 경로가 든 모듈들
from app.errors import register_error_handlers  # 공통 오류 응답 처리기

app = FastAPI(title="Cloud SCM + AX")  # 앱 시작점, 제목은 /docs API 문서에 표시된다
register_error_handlers(app)  # 오류를 {"error": {...}} 모양으로 맞춘다
app.include_router(health.router, prefix="/api/v1")  # 모든 경로 앞에 /api/v1을 붙여 등록한다
app.include_router(auth.router, prefix="/api/v1")  # 가입·로그인·로그아웃·내 정보
