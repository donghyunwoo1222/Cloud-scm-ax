from typing import Annotated  # 타입에 부가 정보(의존성)를 붙이는 도구

from fastapi import Depends  # 의존성 주입
from sqlalchemy import create_engine  # DB 연결 묶음(엔진)을 만드는 함수
from sqlalchemy.orm import Session, sessionmaker  # 세션(DB와 대화하는 작업 단위)을 찍어 내는 틀

from app.config import settings  # .env·환경 변수에서 읽은 DB 주소

engine = create_engine(settings.database_url, pool_pre_ping=True)  # 쓰기 전에 연결이 살아 있는지 확인해 끊긴 연결 오류를 줄인다
SessionLocal = sessionmaker(bind=engine)  # 요청마다 SessionLocal()로 세션을 하나씩 만든다

# 여러 번 나눠 읽는 계산(추천·재고 상태·대시보드)은 트랜잭션 전체를 한 시점의 DB 모습으로 읽는다.
# 기본(READ COMMITTED)은 문장마다 그 순간을 읽어서, 현재고(입고 전 0)와 진행 중 수량(입고 후 0)이 섞이면 가용재고가 0이 된다(#84)
SNAPSHOT = {"isolation_level": "REPEATABLE READ"}  # 첫 조회 순간의 모습을 트랜잭션 끝까지 본다 (읽기 전용 경로에만 쓴다)
ReadSessionLocal = sessionmaker(bind=engine.execution_options(**SNAPSHOT))  # 같은 연결 묶음, 격리 수준만 다르다


def get_db():
    """경로 함수에 세션을 하나 빌려주고, 요청이 끝나면 닫는다 (FastAPI 의존성)."""
    db = SessionLocal()  # 이 요청 전용 세션
    try:
        yield db  # 경로 함수가 쓰는 동안 빌려준다
    finally:
        db.close()  # 성공하든 실패하든 닫는다 (커밋 안 된 작업은 버려진다)


DB = Annotated[Session, Depends(get_db)]  # 경로 함수에서 `db: DB` 한 줄로 세션을 받는 약속


def get_read_db():
    """읽기 전용 계산 경로용 세션: 한 시점의 모습으로 읽는다(SNAPSHOT). 쓰기·잠금에는 쓰지 않는다."""
    db = ReadSessionLocal()  # 이 요청 전용 읽기 세션 (로그인 확인은 get_db 세션이 따로 한다)
    try:
        yield db  # 경로 함수가 쓰는 동안 빌려준다
    finally:
        db.close()  # 닫는다 (읽기만 했으므로 확정할 것이 없다)


ReadDB = Annotated[Session, Depends(get_read_db)]  # 추천·재고·대시보드 조회 경로에서 `db: ReadDB`
