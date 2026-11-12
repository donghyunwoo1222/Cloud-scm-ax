from pathlib import Path  # 파일 경로를 다루는 표준 도구

from pydantic import Field, SecretStr  # 값 길이 같은 검사 조건, 출력해도 값이 가려지는 비밀 글자
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
    # Gemini 연결. 키나 모델 이름이 비면 연결하지 않는다(= 꺼짐). 모델 이름은 기본값을 두지 않는다
    llm_api_key: SecretStr = SecretStr("")  # LLM_API_KEY: Gemini API 키. 출력·repr 에서 ********** 로 가려진다
    llm_model: str = ""  # LLM_MODEL: Gemini 모델 이름
    llm_timeout_seconds: float = Field(8, gt=0)  # LLM_TIMEOUT_SECONDS: 한 번 시도에서 기다리는 최대 초
    llm_deadline_seconds: float = Field(20, gt=0)  # LLM_DEADLINE_SECONDS: 시도·재시도 대기를 합친 마감 초
    llm_max_retries: int = Field(2, ge=0)  # LLM_MAX_RETRIES: 429·5xx·시간 초과 때 다시 시도하는 횟수
    llm_retry_wait_seconds: float = Field(0.5, ge=0)  # LLM_RETRY_WAIT_SECONDS: 첫 재시도 전 대기 초(다음은 2배씩)
    llm_max_input_chars: int = Field(20_000, gt=0)  # LLM_MAX_INPUT_CHARS: 보내는 데이터(JSON 글자 수) 상한
    llm_max_output_tokens: int = Field(1024, gt=0)  # LLM_MAX_OUTPUT_TOKENS: 모델이 낼 수 있는 출력 토큰 상한
    llm_max_response_bytes: int = Field(200_000, gt=0)  # LLM_MAX_RESPONSE_BYTES: 받는 응답 크기 상한(바이트)
    llm_price_input_usd_per_mtok: float = Field(0, ge=0)  # LLM_PRICE_INPUT_USD_PER_MTOK: 입력 100만 토큰당 달러(무료 키 0)
    llm_price_output_usd_per_mtok: float = Field(0, ge=0)  # LLM_PRICE_OUTPUT_USD_PER_MTOK: 출력 100만 토큰당 달러(무료 키 0)


settings = Settings()  # 앱 어디서나 import 해서 쓰는 설정 한 벌
