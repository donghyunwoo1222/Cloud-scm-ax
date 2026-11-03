from typing import Annotated  # 타입에 부가 정보(의존성)를 붙이는 도구

from fastapi import Depends  # 의존성 주입
from sqlalchemy import create_engine  # DB 연결 묶음(엔진)을 만드는 함수
from sqlalchemy.orm import Session, sessionmaker  # 세션(DB와 대화하는 작업 단위)을 찍어 내는 틀

from app.config import settings  # .env·환경 변수에서 읽은 DB 주소

engine = create_engine(settings.database_url, pool_pre_ping=True)  # 쓰기 전에 연결이 살아 있는지 확인해 끊긴 연결 오류를 줄인다
SessionLocal = sessionmaker(bind=engine)  # 요청마다 SessionLocal()로 세션을 하나씩 만든다


def get_db():
    """경로 함수에 세션을 하나 빌려주고, 요청이 끝나면 닫는다 (FastAPI 의존성)."""
    db = SessionLocal()  # 이 요청 전용 세션
    try:
        yield db  # 경로 함수가 쓰는 동안 빌려준다
    finally:
        db.close()  # 성공하든 실패하든 닫는다 (커밋 안 된 작업은 버려진다)


DB = Annotated[Session, Depends(get_db)]  # 경로 함수에서 `db: DB` 한 줄로 세션을 받는 약속
