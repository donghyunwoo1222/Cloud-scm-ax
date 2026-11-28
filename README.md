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

### 운영 메일 설정

운영에서 HTTP API로 메일을 보내려면 백엔드 환경에 `MAIL_PROVIDER=resend`, `RESEND_API_KEY`, `RESEND_FROM`을 설정한다. 발주서·납기 독촉·관리자 인증코드·비밀번호 재설정 메일에 공통으로 적용된다. 운영 전 발신 도메인 확인 필요. [Resend 발송 API 문서](https://resend.com/docs/api-reference/emails/send-email)

로컬 Docker에서는 기본값 `MAIL_PROVIDER=smtp`로 Mailpit을 쓴다.

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

### 7. 시연용 데이터

개발용 시드와 별도로, 시연 회사 한 곳에 생활용품 6개, 32일치 판매, 입출고·실사 조정 및 국내 발주 사례를 추가한다. 발주 화면에서는 발주 상태 5가지와 변경·메일 이력을 볼 수 있다. 초안 편집에서 직전 단가 대비 25% 상승·20% 하락 경고(기본 기준 10%)를 볼 수 있다. 재고가 부족한 품목 2개는 발주 추천에 나온다.

`backend`에서 `DATABASE_URL`을 마이그레이션한 전용 시연 DB로 설정하고, URL의 호스트를 `ALLOW_DEMO_HOST`에 직접 지정한다. 예를 들어 URL 호스트가 `127.0.0.1`이면 다음과 같이 실행한다.

```powershell
$env:ALLOW_DEMO_HOST = "127.0.0.1"
.venv\Scripts\python -m scripts.demo_data
```

운영 모드(`APP_ENV=production`), 테스트 DB, URL 쿼리 옵션 또는 접속 대상을 바꿀 수 있는 `PGHOST` 등 환경변수가 있으면 DB 연결 전에 종료한다. 기존 시연 회사가 있으면 중단하며, 재시연용 데이터가 필요하면 새 전용 DB를 사용한다.

로그인 계정이 필요하면 **최초 실행 전에** `DEMO_ADMIN_PASSWORD`와 `DEMO_STAFF_PASSWORD`를 각각 환경변수로 설정하고 명령에 `--with-accounts`를 붙인다. 계정은 `admin@scm-demo.invalid`, `staff@scm-demo.invalid`다. 관리자 메일 인증은 앱 설정을 따르므로, 인증코드가 켜진 환경에서는 로컬 테스트 메일함에서 코드를 받아야 한다. 발주 메일 기록은 화면 시연용이며 실제 발송은 일어나지 않는다.

## 알려진 한계

- **사용자 테스트**: 하지 않았습니다. 실제 사용자의 사용성 검증 없이 개발자 본인과 자동 테스트로 확인했습니다.
- **해외 발주**: 외화·환율·수입 발주는 배포 범위에서 뺐습니다. 코드의 기반은 있으나 기능 스위치(`FX_ENABLED`)로 꺼져 있습니다.
- **판매 분석**
  - 판매 출고(SALE)의 수량만 집계합니다. 판매 금액은 저장하지 않아 매출 기준 분석은 하지 않습니다. 폐기·기타 출고는 판매에서 뺍니다.
  - 일평균과 소진 예상일은 선택한 기간과 상관없이 최근 30일 판매의 단순 평균입니다. 계절성이나 행사 효과는 반영하지 못합니다.
  - 첫 기록이 14일 미만인 품목은 숫자 대신 "데이터 부족"으로 표시합니다.
  - 소진 예상일은 입고 예정을 포함해 계산하고, "곧 소진" 판단은 발주 추천과 같은 규칙을 씁니다. 기본 공급업체가 없거나 비활성인 품목은 "발주 정보 없음"으로 표시합니다.
- **가져오기(판매·입고·품목)**
  - 한 번에 데이터 5,000행까지 올릴 수 있습니다. 넘으면 일부만 처리하지 않고 거절합니다.
  - 같은 파일을 다시 올려도 (주문번호, 품목) 줄 단위로 이미 반영된 줄은 건너뜁니다. 다만 주문번호를 비우고 직접 입력한 줄은 같은 파일을 다시 올리면 두 번 반영될 수 있습니다.
  - 판매 파일의 날짜에 시각(예: UTC)이 붙어 있으면 시각을 버리고 적힌 날짜를 그대로 씁니다. 시간대를 서울로 바꾸지 않습니다.
- **세금계산서 수취 기록**
  - 월 합계 계산서는 지원하지 않습니다(발주서 단위로만 기록).
  - 운송비가 포함된 계산서는 입고 금액과 "차이"로 표시됩니다.
  - 공급업체의 품목별 반올림 때문에 1원 안팎 차이가 날 수 있고, 이 경우 차이로만 표시합니다.
  - 이 정보는 내부용이며 공급업체에게 가는 문서·메일에는 나오지 않습니다.
- **운영 환경(무료 호스팅 사용 시)**: 백엔드를 무료 인스턴스에 올리면 일정 시간 요청이 없을 때 꺼져서 첫 접속에 최대 1분 걸릴 수 있습니다. 서버가 다시 시작되면 메모리에 두는 로그인 잠금·횟수 제한이 초기화됩니다. 인스턴스는 1개로 운영하는 것을 전제로 합니다.

향후 계획: 이전 기간 비교, CSV 내보내기, 금액 기준 분석, 사용자 테스트.

## 문서
- [docs/](docs/) 기획·설계·검증 문서

## 내 역할
(기획, DB, 개발, AX, 배포 중 직접 한 부분)
