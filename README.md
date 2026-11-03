# 중소기업용 Cloud SCM + AX

중소 유통업체가 품목·공급업체·입출고·재고·발주를 웹에서 관리하고, 재고 부족·과잉을 AI로 미리 알 수 있는 Cloud SCM MVP입니다.

## 문제
(문제 정의를 2~3문장으로 요약)

## 주요 기능
(MVP 기능 목록)

## 서비스 URL / 시연 영상
(배포 후 추가)

## 로컬 실행 방법

준비물: Git, Docker Desktop(실행 중), Python 3.14, Node.js 24. 명령은 PowerShell 기준이고, 별말이 없으면 저장소 맨 위 폴더에서 실행한다.

| 무엇 | 주소 |
| --- | --- |
| 프론트(Next.js) | http://localhost:3000 |
| 백엔드(FastAPI) | http://localhost:8001 (API 문서: http://localhost:8001/docs) |
| PostgreSQL | 내 컴퓨터에서 `localhost:5433`, Docker 안에서 `db:5432` |

### 1. 환경 변수 파일 만들기 (처음 한 번)

```powershell
Copy-Item .env.example .env
```

DB 주소는 실행 위치에 따라 두 가지다.

- 백엔드가 Docker 안에서 돌 때: `postgresql+psycopg://scm:scm_local_pw@db:5432/scm` (`docker-compose.yml`이 직접 넣는다)
- 내 컴퓨터에서 테스트·Alembic을 돌릴 때: `postgresql+psycopg://scm:scm_local_pw@localhost:5433/scm` (`.env`의 값)

### 2. DB + 백엔드 띄우기 (Docker)

```powershell
docker compose up --build
```

- 확인: 브라우저에서 http://localhost:8001/api/v1/health → `{"status":"ok"}`
- `backend/` 코드를 저장하면 자동으로 다시 시작된다(다시 빌드할 필요 없음). `requirements.txt`를 바꿨을 때만 `--build`가 필요하다.
- 종료: `Ctrl+C` 후 `docker compose down` (DB 데이터는 남는다. 지우려면 `docker compose down -v`)

### 3. 프론트 띄우기 (새 터미널)

```powershell
cd frontend
npm install
npm run dev
```

- 확인: http://localhost:3000 에 프로젝트 이름이 보인다. `/api/*` 요청은 Next.js가 백엔드(8001)로 전달한다.

### 4. 백엔드 테스트 (로컬 venv)

처음 한 번 가상환경을 만든다.

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

테스트 실행은 항상 이 명령 하나로 한다(CI도 `backend/`에서 같은 `python -m pytest`를 쓴다).

```powershell
cd backend
.venv\Scripts\python -m pytest
```

Alembic(표 변경 이력)도 `backend/`에서 `.venv\Scripts\alembic <명령>`으로 실행하며, `.env`의 `localhost:5433` 주소를 쓴다(Docker DB가 떠 있어야 한다).

## 문서
- [docs/](docs/) 기획·설계·검증 문서

## 내 역할
(기획, DB, 개발, AX, 배포 중 직접 한 부분)
