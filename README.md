# 중소기업용 Cloud SCM + AX

중소 규모의 로트·유통기한 관리가 필요 없는 공산품·생활용품 유통업체가 품목·공급업체·입출고·재고·발주를 웹에서 관리하고, 재고 부족·과잉을 AI로 미리 알 수 있는 Cloud SCM MVP입니다.

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

`.env`의 `SECRET_KEY`를 32자 이상 임의 문자열로 바꾼다(그대로 두면 백엔드가 시작하지 않는다). 아래 명령의 출력을 붙여 넣으면 된다.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
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

테스트 실행은 항상 이 명령 하나로 한다(CI도 `backend/`에서 같은 `python -m pytest`를 쓴다). DB 제약 테스트가 있으므로 2번의 Docker DB가 떠 있어야 한다. 테스트는 개발용 DB(`scm`)가 아니라 같은 컨테이너의 테스트 전용 DB(`scm_test`, 없으면 자동 생성)를 쓰고, 실행할 때마다 표를 지우고 마이그레이션으로 다시 만든다. 다른 DB를 쓰려면 환경 변수 `TEST_DATABASE_URL`을 준다.

```powershell
cd backend
.venv\Scripts\python -m pytest
```

Alembic(표 변경 이력)도 `backend/`에서 `.venv\Scripts\alembic <명령>`으로 실행하며, `.env`의 `localhost:5433` 주소를 쓴다(Docker DB가 떠 있어야 한다).

### 5. 린트 실행

린트는 코드 규칙 위반을 찾는 검사다. PR을 올리면 CI(GitHub Actions)가 4번 테스트와 함께 자동으로 돌린다. 백엔드는 `cd backend; .venv\Scripts\python -m ruff check .`, 프론트는 `cd frontend; npm run lint`로 실행한다.

### 6. 개발용 시드 데이터

화면 확인용 샘플(회사 2곳, 회사마다 관리자·담당자 1명, 공급업체 2개, 품목 5개)을 개발 DB(`scm`)에 넣는다. Docker DB가 떠 있고 `alembic upgrade head`를 한 뒤에 실행한다. 테스트 DB(`scm_test`)에는 넣지 않는다.

개발용 시드 데이터는 배포 DB에는 넣지 않는다.

```powershell
cd backend
.venv\Scripts\python -m scripts.seed
```

다시 실행하면 시드를 지우고 새로 넣는다. 시드만 지우려면 `.venv\Scripts\python -m scripts.seed --clear`. 시드 계정(개발용 비밀번호 `seed-pass-1234`):

| 회사 | 관리자 | 담당자 |
| --- | --- | --- |
| 가나패션(시드) | admin.gana@seed.local | staff.gana@seed.local |
| 사아마트(시드) | admin.saa@seed.local | staff.saa@seed.local |

## 문서
- [docs/](docs/) 기획·설계·검증 문서

## 내 역할
(기획, DB, 개발, AX, 배포 중 직접 한 부분)
