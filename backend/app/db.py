from sqlalchemy import create_engine  # DB 연결 묶음(엔진)을 만드는 함수
from sqlalchemy.orm import sessionmaker  # 세션(DB와 대화하는 작업 단위)을 찍어 내는 틀

from app.config import settings  # .env·환경 변수에서 읽은 DB 주소

engine = create_engine(settings.database_url, pool_pre_ping=True)  # 쓰기 전에 연결이 살아 있는지 확인해 끊긴 연결 오류를 줄인다
SessionLocal = sessionmaker(bind=engine)  # 요청마다 SessionLocal()로 세션을 하나씩 만든다
