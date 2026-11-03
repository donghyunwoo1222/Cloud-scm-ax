from pathlib import Path  # 파일 경로를 다루는 표준 도구

from pydantic_settings import BaseSettings, SettingsConfigDict  # 환경 변수·.env를 읽는 도구

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"  # 저장소 맨 위의 .env 파일 위치 (backend/app/config.py 기준 두 단계 위)


class Settings(BaseSettings):
    # 환경 변수가 있으면 그 값을, 없으면 .env 파일 값을 쓴다 (Docker에서는 compose가 환경 변수로 넣는다)
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    database_url: str  # DB 주소 (DATABASE_URL), 기본값 없음: 비어 있으면 시작할 때 바로 오류
    secret_key: str  # 로그인 토큰 서명 키 (SECRET_KEY), 기본값 없음: 비밀값을 코드에 넣지 않으려고


settings = Settings()  # 앱 어디서나 import 해서 쓰는 설정 한 벌
