import logging  # DB 확인 실패를 고정 문구로 남긴다

from fastapi import APIRouter, Response  # 경로 묶음과 빈 HTTP 응답
from sqlalchemy import text  # 실행할 SQL 문장
from sqlalchemy.exc import SQLAlchemyError  # DB 접속·쿼리·풀 대기 오류

from app.db import engine  # 앱이 실제로 쓰는 연결 풀

router = APIRouter()  # 이 파일의 경로들을 담을 라우터
probe_router = APIRouter()  # 배포 상태 확인 경로는 /api/v1 밖에 둔다
logger = logging.getLogger(__name__)  # 이 모듈의 로그


@router.get("/health")  # GET /api/v1/health 요청을 받는다 (앞부분 /api/v1은 main.py에서 붙인다)
def health() -> dict[str, str]:
    return {"status": "ok"}  # 서버가 살아 있으면 이 JSON을 200으로 돌려준다


@probe_router.get("/healthz", include_in_schema=False)
def healthz() -> Response:
    return Response(status_code=200)  # 서버가 응답하는지만 확인한다


@probe_router.get("/healthz/db", include_in_schema=False)
def healthz_db() -> Response:
    try:
        with engine.connect() as connection:  # 앱과 같은 풀에서 연결을 빌리고 돌려준다
            connection.execute(text("SELECT 1"))  # 테이블을 읽지 않고 DB가 응답하는지만 확인한다
    except SQLAlchemyError:
        logger.warning("Database health check failed")  # 접속 정보가 들어갈 수 있는 예외 원문은 기록하지 않는다
        return Response(status_code=503)  # 응답에도 상세 정보를 담지 않는다
    return Response(status_code=200)  # 연결과 쿼리가 모두 성공했다
