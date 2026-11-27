# Render Free · Supabase · Vercel 배포 안내

백엔드는 Render Singapore의 Free 인스턴스 1개, 데이터베이스는 Supabase, 프런트엔드는 Vercel에 둔다. 환경 변수의 실제 비밀값은 각 서비스의 설정 화면 또는 내 PC의 현재 셸에만 넣는다. 아래 주소와 접속 형식은 예시다.

## 환경 변수

### 백엔드 · Render

| 이름 | 필수 여부 | 설명 |
| --- | --- | --- |
| `APP_ENV` | 필수 | `production`. 운영 설정을 시작할 때 검사한다. |
| `COOKIE_SECURE` | 필수 | `true`. 로그인 쿠키를 HTTPS에서만 전송한다. |
| `SECRET_KEY` | 필수 | 로그인 토큰 서명용으로 새로 생성한 32자 이상의 임의 값. |
| `APP_BASE_URL` | 필수 | 사용자가 접속할 Vercel 프런트 주소. 예: `https://scm.example.invalid`. 메일 링크에도 쓰인다. |
| `DATABASE_URL` | 필수 | Supabase **Session pooler**의 5432번 포트. 예: `postgresql+psycopg://postgres.demo-ref:URL_ENCODED_PASSWORD@pooler.example.invalid:5432/postgres`. |
| `PGSSLMODE` | 이 가이드의 설정 | `require`. DB 접속을 TLS로 암호화한다. URL 쿼리 대신 별도 변수로 두면 데모 스크립트에서도 같은 URL 형식을 쓸 수 있다. |
| `MAIL_PROVIDER` | 필수 | 이 가이드에서는 `resend`. Resend에서 발신 도메인을 먼저 확인한다. |
| `RESEND_API_KEY` | Resend 사용 시 필수 | Resend API 키. |
| `RESEND_FROM` | Resend 사용 시 필수 | 확인한 도메인의 발신 주소. 예: `scm@example.invalid`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY` | SMTP를 선택할 때 필요 | `MAIL_PROVIDER=smtp`일 때 쓰는 호스트·포트·암호화 방식. 기본은 587과 `starttls`다. Render Free는 25·465·587번 SMTP 포트의 발신을 막으므로 이 가이드에서는 Resend HTTP API를 사용한다. |
| `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | SMTP를 선택할 때 필요 | 메일 서버 계정·비밀번호·발신 주소. 계정이 필요한 SMTP 서버에서 설정한다. |
| `ADMIN_OTP_ENABLED` | 선택 | 기본 `true`. 관리자 로그인에 메일 인증코드를 요구한다. |
| `API_DOCS_ENABLED` | 선택 | 운영 기본 `false`. `true`면 API 문서가 공개된다. |
| `FX_ENABLED` | 선택 | 기본 `false`. 외화 발주서의 문서·엑셀·메일을 열 때 `true`로 설정한다. |
| `DB_POOL_SIZE` | 선택 | 기본 `5`, 1 이상의 정수. 재사용할 연결 수다. |
| `DB_MAX_OVERFLOW` | 선택 | 기본 `5`, 0 이상의 정수. 바쁠 때 임시로 더 쓸 수 있는 연결 수다. |
| `DB_POOL_RECYCLE` | 선택 | 기본 `1800`, 0 이상의 정수(초). 오래된 연결은 다음 대여 때 교체한다. |
| `PORT` | Render에서 자동 제공 | Docker 시작 명령이 이 포트에서 Uvicorn 워커 1개를 실행한다. |

DB 풀은 접속을 여러 요청이 재사용할 수 있게 보관하는 묶음이다. 기본값으로 워커 1개가 동시에 빌려줄 수 있는 앱 연결은 최대 10개(기본 5개 + 임시 5개)다.

### 프런트엔드 · Vercel

| 이름 | 필수 여부 | 설명 |
| --- | --- | --- |
| `BACKEND_URL` | 필수 | Render 백엔드의 HTTPS 주소. 예: `https://scm-api.example.invalid`. 끝에 슬래시나 `/api`를 붙이지 않는다. Vercel이 브라우저의 `/api/*` 요청을 이 주소로 전달한다. |
| `NEXT_PUBLIC_FX_ENABLED` | 선택 | 기본 `false`. 외화 발주를 켤 때 Render의 `FX_ENABLED`와 함께 `true`로 바꾸고 프런트를 다시 빌드한다. |

## 배포 순서

1. **Supabase 프로젝트 생성.** Free 프로젝트를 만들고 가능한 경우 Render와 같은 싱가포르 리전을 선택한다. 대시보드에서 **Connect → Session pooler**를 열어 호스트·사용자명·DB 이름을 확인한다. 표시된 주소의 접두사를 `postgresql+psycopg://`로 바꾸고 포트가 `5432`인지 확인한다. 비밀번호에 `@` 같은 특수문자가 있으면 URL 인코딩한다(예: `@` → `%40`). [Supabase 연결 안내](https://supabase.com/docs/guides/database/connecting-to-postgres)
2. **내 PC에서 마이그레이션 실행.** 마이그레이션은 DB 표를 만드는 변경 기록이다. 저장소의 `backend`에서 Python 3.14 가상환경을 활성화하고 `python -m pip install -r requirements.txt`를 실행한다. 현재 셸에 대상 Supabase 프로젝트의 `DATABASE_URL`, `PGSSLMODE=require`, 로컬 실행용 `SECRET_KEY`, `APP_ENV=development`를 설정한다. 접속 대상 프로젝트를 확인한 후 `python -m alembic upgrade head`를 실행한다. `python -m alembic current`로 적용한 버전을 확인한다. 새 버전의 스키마를 적용할 때도 이 명령을 내 PC에서 먼저 실행한다.
3. **데모 데이터 생성.** 시연용 프로젝트에서 같은 셸에 `ALLOW_DEMO_HOST`를 설정한다. 값은 DB URL의 풀러 호스트만 복사한다(포트 제외). `python -m scripts.demo_data`를 실행하면 시연 회사가 생긴다. 로그인 가능한 시연 담당자가 필요하면 최초 실행 전에 `DEMO_ADMIN_PASSWORD`와 `DEMO_STAFF_PASSWORD`를 각기 다른 임의 값으로 설정하고 대신 `python -m scripts.demo_data --with-accounts`를 실행한다. 이 명령은 회사와 계정을 한 번만 생성한다. 데모 관리자는 인증코드를 받을 수 없는 예시 주소를 쓰므로, 운영 관리자 로그인은 실제 메일을 받을 수 있는 주소로 준비한다. 작업을 마치면 비밀값을 설정한 셸을 닫는다.
4. **Render 백엔드 생성.** GitHub 저장소의 배포 브랜치를 연결해 **Web Service → Docker → Singapore → Free**를 선택한다. Root Directory는 `backend`, Dockerfile은 그 폴더의 `Dockerfile`을 사용하고 Docker Command는 기본값으로 둔다. 인스턴스는 1개다. 위 표의 환경 변수를 등록하고 **Health Check Path**에 `/healthz`를 넣는다. 프런트의 확정 주소를 `APP_BASE_URL`에 넣는다. Vercel 생성 때 실제 주소가 달라지면 이 값을 수정하고 백엔드를 다시 배포한다. 백엔드 시작 명령에는 마이그레이션이 들어 있지 않다. [Render 웹 서비스](https://render.com/docs/web-services) · [Render 헬스체크](https://render.com/docs/health-checks)
5. **Vercel 프런트 연결.** 같은 저장소로 Next.js 프로젝트를 만들고 Root Directory에 `frontend`를 지정한다. Production 환경에 프런트 변수를 등록하고 배포한다. Render의 `APP_BASE_URL`이 최종 Vercel 주소와 일치하는지 확인한다. 프런트의 회사 가입 화면에서 실제 메일을 받을 수 있는 주소로 관리자 계정을 만들고 로그인과 인증코드 수신을 시험한다. 데모 데이터를 보려면 3단계에서 만든 시연 담당자로 로그인한다. [Vercel 환경 변수](https://vercel.com/docs/environment-variables)
6. **헬스체크.** `curl.exe -i https://scm-api.example.invalid/healthz`와 `curl.exe -i https://scm-api.example.invalid/healthz/db`에서 예시 호스트를 Render 서비스 주소로 바꿔 실행한다. 두 경로 모두 로그인 없이 확인하며 정상은 빈 본문과 HTTP 200이다. 앞 경로는 앱만 확인한다. 뒤 경로는 DB에 `SELECT 1`을 실행하고 접속·쿼리 실패 시 빈 본문과 HTTP 503을 반환한다.
7. **외부 모니터 등록.** 무료 HTTP 모니터가 Render 주소의 `/healthz/db`를 15분보다 짧은 주기(예: 5분)로 호출하도록 설정한다. HTTP 요청은 Render Free의 휴면을 줄이고, 성공한 쿼리는 Supabase Free의 비활성 일시정지를 막기 위한 DB 활동을 만든다. 무료 한도와 모니터 장애에 따라 계속 가동된다는 보장은 없다. [Render Free 제한](https://render.com/docs/free) · [Supabase 일시정지](https://supabase.com/docs/guides/platform/free-project-pausing)

## 알려진 한계

- **휴면과 첫 접속.** Render Free는 15분간 들어오는 요청이 없으면 휴면에 들어간다. 다음 첫 접속에서 다시 뜨기까지 최대 약 1분을 예상한다. [Render Free 제한](https://render.com/docs/free)
- **재시작 시 메모리 제한 초기화.** 로그인 실패·잠금과 비밀번호 재설정 요청 횟수는 프로세스 메모리에 있어 재시작하면 초기화된다. 챗봇의 사용자별 분당 요청 제한도 초기화된다. DB에 기록하는 관리자 OTP 시도·재발송 횟수와 챗봇의 회사별 일일 집계는 유지된다.
- **영구 디스크 없음.** 컨테이너 로컬 디스크에 쓴 파일은 휴면·재시작·재배포 시 사라질 수 있다. 업무 데이터는 Supabase에 저장한다.
- **인스턴스 1개 고정.** Render Free 인스턴스 1개에 Uvicorn 워커 1개를 실행한다. 이 프로세스가 멈추면 다시 시작할 때까지 백엔드 요청을 처리할 수 없다.
