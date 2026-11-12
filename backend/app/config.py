from pathlib import Path  # 파일 경로를 다루는 표준 도구

from pydantic import Field  # 값 길이 같은 검사 조건
from pydantic_settings import BaseSettings, SettingsConfigDict  # 환경 변수·.env를 읽는 도구

ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"  # 저장소 맨 위의 .env 파일 위치 (backend/app/config.py 기준 두 단계 위)


class Settings(BaseSettings):
    # 환경 변수가 있으면 그 값을, 없으면 .env 파일 값을 쓴다 (Docker에서는 compose가 환경 변수로 넣는다)
    model_config = SettingsConfigDict(env_file=ROOT_ENV, extra="ignore")

    database_url: str  # DB 주소 (DATABASE_URL), 기본값 없음: 비어 있으면 시작할 때 바로 오류
    secret_key: str = Field(min_length=32)  # 로그인 토큰 서명 키 (SECRET_KEY), 기본값 없음. 짧으면 추측당하기 쉬워 32자 미만이면 시작 거부
    cookie_secure: bool = False  # COOKIE_SECURE: 배포(HTTPS)에서만 true. true면 쿠키가 HTTPS로만 전송된다
    # 발주서 메일 발송(#158). 코드에 비밀번호를 넣지 않고 환경 변수로만 받는다. SMTP_HOST 가 비면 발송 요청은 503
    smtp_host: str = ""  # SMTP_HOST: 메일 서버 주소 (예: smtp.gmail.com, 로컬은 mailpit)
    smtp_port: int = 587  # SMTP_PORT: 587(STARTTLS) / 465(SSL) / 1025(로컬 mailpit)
    smtp_user: str = ""  # SMTP_USER: 로그인 아이디 (비면 로그인 생략, 로컬 mailpit)
    smtp_password: str = ""  # SMTP_PASSWORD: 로그인 비밀번호 (앱 비밀번호)
    smtp_from: str = ""  # SMTP_FROM: 보내는 주소 하나 (시스템 주소). 답장은 Reply-To 로 담당자에게 간다
    app_base_url: str = ""  # APP_BASE_URL: 재설정 메일 링크의 앞부분 (예: https://scm.example.com). 비면 재설정 요청은 503 (#170)
    smtp_security: str = "starttls"  # SMTP_SECURITY: starttls / ssl / none (none 은 로컬 전용)
    # LLM 공통 호출(#180). 기본은 모두 "꺼짐": 하나라도 꺼져 있으면 LLM 을 부르지 않고 수동 입력으로 안내한다
    llm_enabled: bool = False  # LLM_ENABLED: 전체 스위치(kill switch). false 면 즉시 끈다
    llm_daily_calls_per_company: int = Field(0, ge=0)  # LLM_DAILY_CALLS_PER_COMPANY: 회사별 하루 호출 수. 0 = 꺼짐
    llm_monthly_budget_usd: float = Field(0, ge=0)  # LLM_MONTHLY_BUDGET_USD: 전체 월 비용 한도(달러). 0 = 꺼짐


settings = Settings()  # 앱 어디서나 import 해서 쓰는 설정 한 벌
