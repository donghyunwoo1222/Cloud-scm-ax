# 백엔드 이미지: Python 3.14 위에 라이브러리를 설치하고 FastAPI를 띄운다
FROM python:3.14-slim

# 컨테이너 안 작업 폴더
WORKDIR /app

# 라이브러리 목록을 먼저 복사해 설치 (코드만 바뀌면 이 단계는 캐시를 재사용해 빨라진다)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 코드 복사
COPY . .

# Render가 준 포트로 워커 하나를 실행한다. 로컬 Compose는 개발용 명령으로 덮어쓴다.
CMD ["sh", "-c", "exec uvicorn app.main:app --no-proxy-headers --host 0.0.0.0 --port \"${PORT:-8000}\" --workers 1"]
