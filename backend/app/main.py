from fastapi import FastAPI  # FastAPI 앱 클래스

from app.api import health  # health 경로가 든 모듈

app = FastAPI(title="Cloud SCM + AX")  # 앱 시작점, 제목은 /docs API 문서에 표시된다
app.include_router(health.router, prefix="/api/v1")  # 모든 경로 앞에 /api/v1을 붙여 등록한다
