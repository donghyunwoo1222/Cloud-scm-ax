# API 설계: 엔드포인트·권한·오류 규칙

2026-11-03 (초안, 검토 전)

## 설계 원칙

이 문서는 ERD의 7개 표와 확정된 업무 규칙(R1\~R10)을 화면이 부를 수 있는 API로 옮긴다. 기술 스택은 FastAPI로 임시 확정했지만(아키텍처 문서), 여기서는 스택과 무관한 REST 형태로 적는다. "확정"은 사용자가 정한 것, "임시 확정"은 사용자가 판단을 맡겨 정한 것이라 나중에 바꿀 수 있고, "제안"은 이 초안에서 고른 것이라 검토 후 바뀔 수 있다.

| 항목 | 내용 | 상태 |
| --- | --- | --- |
| 방식 | REST, JSON. 경로는 `/api/v1/` 뒤에 복수 명사 | 임시 확정 |
| 회사 분리 | 요청에 company\_id를 받지 않는다. 로그인한 사용자의 회사를 서버가 모든 조회·저장에 붙인다(R1) | 확정 |
| 인증 | 이메일과 비밀번호로 로그인하면 서버가 토큰을 쿠키로 내려주고, 브라우저가 이후 요청마다 자동으로 보낸다. 토큰에서 사용자·회사·역할을 읽는다. 쿠키는 httpOnly, SameSite=Lax, 배포 환경에서는 Secure | 확정 |
| 요청 주소 | 브라우저는 Next.js 주소로만 요청하고, Next.js가 `/api/*`를 FastAPI로 전달한다(rewrites). 브라우저 입장에서 같은 주소라 CORS 설정이 필요 없다 | 확정 |
| CSRF 방어 | 상태를 바꾸는 요청은 POST/PATCH만 쓰고, GET은 읽기만 한다 | 확정 |
| 재고 | 재고를 직접 고치는 API는 없다. 입출고 이력을 등록해야만 재고가 바뀐다(R2) | 확정 |
| 음수 재고 | 출고·재고 조정·정정 등록은 서버 트랜잭션 안에서 그 품목 줄을 잠그고 합계를 확인한 뒤 저장한다(R3) | 확정 |
| 삭제 | 공급업체·품목은 삭제하지 않고 항상 비활성(`is_active`)으로 바꾼다. 삭제 기능(DELETE)은 없다 | 확정 |
| 비활성 범위 | 비활성은 새 발주에만 안 나온다: 새 발주서 작성·품목 추가·추천 목록·초안 생성에서 제외, 비활성이 든 DRAFT는 승인 때 막음. 출고·조정·정정, 이미 ORDERED인 발주의 입고, 발주 없는 직접 입고는 허용(반품처럼 발주 없이 돌아오는 물건도 받아야 한다) | 확정 |
| 이력 수정 | 입출고 이력은 수정·삭제 API를 두지 않는다. 잘못 넣은 건 정정 이력(`POST /inventory-movements/{id}/corrections`)으로 바로잡는다 | 확정 |
| 소수와 올림 | 일평균·재주문점·비교는 소수 그대로 계산하고, 최종 추천 수량만 올림(ceil)한다. 화면·이유 문구의 일평균은 소수 첫째 자리까지 표시 | 확정 |
| 성공 응답 | `{"data": …}` 형태. 목록은 `data`에 배열, `meta`에 쪽수 정보 `{"page", "page_size", "total"}`(#24) | 임시 확정 |
| 오류 응답 | `{"error": {"code": "…", "message": "…", "details": …}}`. code는 영문 대문자 이름, message는 화면에 그대로 보여줄 한국어 | 임시 확정 |
| 날짜·시간 | ISO 8601 문자열. "최근 30일" 같은 날짜 경계는 회사 시간대(기본 Asia/Seoul) 기준 | 임시 확정 |
| 목록 | `page`, `page_size`(기본 20, 최대 100), `q`(검색어)와 필터를 쿼리로 받는다. 정렬은 최신순. 비활성 행은 기본으로 숨기고 `include_inactive=true`일 때 포함한다(#24) | 임시 확정 |
| SKU | 앞뒤 공백을 지우고 대문자로 바꿔 저장·비교한다(`ts-bk-m`과 `TS-BK-M`은 같은 품목, #26) | 임시 확정 |
| 공급업체명 | 앞뒤 공백만 지우고 대소문자는 구분한다(한글 이름이 대부분이라 바꾸지 않음, #26) | 임시 확정 |

회사 분리를 요청에서 받지 않는 이유는 간단하다. 요청에 company\_id를 넣게 하면 다른 회사 값을 넣어 보는 일이 가능해지고, 서버가 그때마다 막아야 한다. 토큰에서 읽으면 그 경로 자체가 없어진다. 존재하지 않는 id와 다른 회사의 id는 둘 다 404로 답해, 다른 회사 데이터가 있는지조차 알 수 없게 한다(S8).

## 엔드포인트 목록

기능(F1\~F8)별로 묶었다. 역할은 두 개다(임시 확정): 관리자 ADMIN(승인·계정 관리 가능), 담당자 STAFF(구매·재고·입출고 담당). 권한은 인터뷰 결과를 반영하기 전까지 모두 임시 확정이다. `{id}`는 경로 자리표시자다.

| 기능 | 방식과 경로 | 하는 일 | 허용 역할 |
| --- | --- | --- | --- |
| F1 회사·사용자 | POST /companies | 회사와 처음 관리자 계정 등록 | 누구나(로그인 전) |
| F1 | POST /auth/login, POST /auth/logout | 로그인·로그아웃 | 누구나 |
| F1 | GET /me | 내 정보·회사·역할 | 둘 다 |
| F1 | GET /users, POST /users, PATCH /users/{id} | 직원 목록, 이메일·임시 비밀번호로 계정 생성, 역할·비활성 변경 | 관리자 |
| F2 공급업체 | GET /suppliers, POST /suppliers | 목록(비활성 제외·포함 선택), 등록(리드타임 0 이상 정수) | 둘 다 |
| F2 | GET /suppliers/{id}, PATCH /suppliers/{id} | 상세, 수정·비활성 | 둘 다 |
| F3 품목 | GET /products, POST /products | 목록, 등록(기본 공급업체 필수) | 둘 다 |
| F3 | GET /products/{id}, PATCH /products/{id} | 상세, 수정·비활성 | 둘 다 |
| F4 입출고 | POST /inventory-movements | 직접 입고, 출고(판매·폐기·기타), 재고 조정 등록. movement\_type으로 구분 | 둘 다 |
| F4 | POST /inventory-movements/{id}/corrections | 잘못 넣은 이력 {id}를 정정(CORRECTION 등록) | 둘 다 |
| F4 | GET /inventory-movements | 이력 조회(품목·유형·기간 필터) | 둘 다 |
| F5 현재 재고 | GET /stock, GET /stock/{product\_id} | 품목별 현재고(이력 합계)와 안전재고. 상태(가용재고 ≤ 재주문점이면 부족, 추천과 같은 기준)는 #39에서 추가 | 둘 다 |
| F6 발주 | GET /purchase-orders, POST /purchase-orders | 목록, DRAFT 발주서 만들기(직접) | 둘 다 |
| F6 | GET /purchase-orders/{id}, PATCH /purchase-orders/{id} | 상세, DRAFT 일 때만 품목·수량 수정 | 둘 다 |
| F6 | POST /purchase-orders/{id}/approve | DRAFT → APPROVED | 관리자 |
| F6 | POST /purchase-orders/{id}/order | APPROVED → ORDERED(공급업체에 발주했음 표시) | 둘 다 |
| F6 | POST /purchase-orders/{id}/receipts | 발주 품목 입고(부분 가능). 이력 등록 + 상태 갱신을 한 번에 | 둘 다 |
| F6 | POST /purchase-orders/{id}/cancel | 입고 이력이 없는 발주만 취소 | 둘 다 |
| F7 대시보드 | GET /dashboard | 부족·과잉·진행 중 발주 요약 | 둘 다 |
| F8 발주 추천 | GET /recommendations | 현재 시점 추천 목록 계산·반환 | 둘 다 |
| F8 | POST /recommendations/drafts | 선택한 품목으로 공급업체별 DRAFT 발주서 생성·품목 추가 | 둘 다 |

합계 엔드포인트는 약 25개다. 발주 상태 변경을 PATCH의 status 칸으로 하지 않고 동사 경로(approve, order, cancel)로 나눴다. 이렇게 하면 "승인은 관리자만", "취소는 입고 없을 때만" 같은 규칙을 경로 하나에 하나씩 붙일 수 있고, 상태를 건너뛰는 요청(승인 생략)이 경로에서부터 존재하지 않는다(R5).

## 핵심 API 상세

업무 규칙이 가장 많이 들어가는 것만 자세히 적는다. 요청·응답의 칸 이름은 ERD의 칸 이름과 같다.

### 1) 출고 등록: POST /inventory-movements

```json
{
  "product_id": 12,
  "movement_type": "SALE",
  "quantity": 12,
  "sales_channel": "OWN_MALL",
  "movement_date": "2026-11-03"
}
```

요청의 quantity는 항상 1 이상 양수다. 늘고 줌(direction)은 서버가 movement\_type을 보고 정해 이력에 저장한다. 판매 채널은 movement\_type이 SALE일 때만 필수다(R7). 재고 조정은 같은 경로에 `"movement_type": "ADJUSTMENT"`, `"direction": "IN"` 또는 `"OUT"`, 필수 `"reason"`을 넣어 보낸다(R10). 조정은 재고 실사 차이 전용이고, 잘못 넣은 이력은 아래 2)의 정정으로 바로잡는다.

서버는 한 트랜잭션 안에서 ① 품목 줄을 잠그고 ② 현재고(이력 합계)를 읽고 ③ 빼고 난 값이 0 미만이면 저장하지 않고 오류를 돌려준다(R3). 재고 52개인 품목에 동시에 30개씩 두 건이 와도 한 건만 성공한다. 비활성 품목이어도 출고·조정과 발주 없는 직접 입고는 허용한다(남은 재고가 묶이지 않게, 반품처럼 발주 없이 돌아오는 물건도 받아야 한다).

```json
// 409 Conflict
{
  "error": {
    "code": "INSUFFICIENT_STOCK",
    "message": "현재고 52개보다 많이 출고할 수 없습니다.",
    "details": { "current_stock": 52, "requested": 60 }
  }
}
```

성공하면 201과 함께 등록된 이력과 등록 직후 재고(`stock_after`)를 돌려준다. 화면이 바로 재고 숫자를 갱신할 수 있다.

`movement_date`를 비우면 서울 기준 오늘로 저장한다. 미래 날짜는 422 `VALIDATION_ERROR`, 과거 날짜는 허용한다(늦게 입력하는 경우). 아직 일어나지 않은 입출고가 재고·30일 판매에 섞이지 않게 하기 위해서다(#29, 임시 확정). 이 경로는 `purchase_order_item_id`와 `CORRECTION`을 받지 않는다(422): 발주 입고는 3), 정정은 2)로만 한다.

### 2) 잘못 넣은 이력 정정: POST /inventory-movements/{id}/corrections

```json
{
  "quantity": 90,
  "reason": "판매 10개를 100개로 잘못 입력"
}
```

경로의 {id}가 바로잡을 원래 이력이다. 서버는 CORRECTION 이력 한 줄을 쌓는다. reverses\_movement\_id는 {id}, 품목은 원래 이력과 같고, direction은 원래 이력의 반대다. 원래 이력이 발주 입고면 purchase\_order\_item\_id도 원래 이력과 같은 값으로 넣는다. quantity와 reason은 필수다.

- 원래 이력이 없거나 다른 회사 이력이면 404 `NOT_FOUND`
- 원래 이력이 CORRECTION이면(정정의 정정) 422 `VALIDATION_ERROR`(임시 확정)
- 그 이력에 대한 정정 수량 합계가 원래 수량을 넘으면 409 `CORRECTION_EXCEEDS`
- 원래 이력이 발주 입고인데 발주가 ORDERED가 아니면 409 `INVALID_STATUS`. RECEIVED가 된 발주의 입고는 정정할 수 없다(한계)
- 정정 때문에 재고가 0 미만이 되면 409 `INSUFFICIENT_STOCK`. 출고 등록과 같이 품목 줄을 잠그고 검사한다(R3)
- 비활성 품목이어도 정정은 허용한다

예) 판매 100개(#51)를 잘못 넣고 정정 90개를 보내면, 재고는 −10만큼만 줄고 30일 판매 합계는 10이 된다(S13). 성공 응답은 출고 등록과 같다(201, 이력과 `stock_after`).

정정 이력의 `movement_date`는 원래 이력의 날짜를 따른다(날짜로 묶는 집계가 따로 챙기지 않아도 맞게, 고친 시각은 `created_at`). 실사 조정(ADJUSTMENT)도 정정할 수 있다. 발주 없는 직접 입고의 정정은 상태 검사 없이 재고 검사만 한다. 잠금 순서는 발주서 → 품목이다(발주 입고와 같은 순서로 교착 방지). 같은 원래 이력에 대한 동시 정정도 품목 줄 잠금으로 한 줄로 세워 합계가 원래 수량을 넘지 않는다(#30, 임시 확정).

### 3) 발주 입고: POST /purchase-orders/{id}/receipts

```json
{
  "movement_date": "2026-11-10",
  "items": [
    { "purchase_order_item_id": 301, "quantity": 40 }
  ]
}
```

한 트랜잭션에서 품목별 입고 이력(RECEIPT)을 쌓고, 누적 입고량을 계산해 발주 상태를 정한다. 부분 입고면 ORDERED 유지, 모든 품목이 다 찬 뒤에만 RECEIVED다. 누적 입고량이 발주 수량을 넘으면 409 `OVER_RECEIPT`, 상태가 ORDERED가 아니면 409 `INVALID_STATUS`로 막는다. 누적 입고량은 연결된 RECEIPT 합계에서 연결된 CORRECTION 합계를 뺀 값이다. 품목이나 공급업체가 비활성이 되었어도 이미 ORDERED인 발주의 입고는 허용한다. 응답에는 갱신된 발주 상태와 품목별 누적 입고량을 담는다.

행 잠금 순서는 회사 → 발주서 → 품목이고, 여러 품목은 품목 번호 순으로 잠근다(교착 방지, PROGRESS.md의 행 잠금 순서).

입고일(`movement_date`)은 비우면 서울 오늘, 미래 날짜는 422(직접 입고와 같은 규칙). 한 요청의 모든 줄을 먼저 검사해 하나라도 넘치면 아무것도 저장하지 않는다(초과 메시지에 남은 수량, details에 `remaining`). 같은 줄을 두 번 보내면 422, 이 발주서에 없는 줄은 404. RECEIVED가 되면 `received_at`은 이 발주서 입고 이력 중 가장 늦은 입고일이다(erd.md). 응답은 201과 갱신된 발주서(`GET /purchase-orders/{id}`와 같은 모양)다(#35).

### 4) 발주 상태 변경: approve · order · cancel

세 경로 모두 요청 본문이 없다. 서버가 현재 상태를 보고 허용되는 한 단계만 바꾼다(DRAFT→APPROVED→ORDERED). 그 밖의 요청은 409 `INVALID_STATUS`, 담당자가 approve를 부르면 403 `FORBIDDEN_ROLE`(S11), 입고 이력이 있는 발주의 cancel은 409 `CANNOT_CANCEL_RECEIVED`이다(입고 후 전부 정정해 누적 입고량이 0이어도 RECEIPT 기록이 있으면 마찬가지, 임시 확정). 비활성 공급업체나 비활성 품목이 든 DRAFT를 approve하면 409 `INACTIVE_REFERENCE`이다. 마지막 상태 변경은 모두 한 번에 하나씩만 되도록 서버가 현재 상태를 읽고 갱신하는 조건을 한 구문에서 검사한다(두 명이 동시에 눌러도 한 번만 반영).

상태 변경이 다른 행을 함께 잠가야 하면 회사 → 발주서 → 품목 순서를 지킨다(PROGRESS.md의 행 잠금 순서).

허용 이동 표(#34). 여기 없는 이동은 모두 409 `INVALID_STATUS`다. RECEIVED는 입고(3))가 모든 품목이 다 찬 뒤에 정한다.

| 경로 | 출발 상태 | 도착 상태 | 역할 | 추가 검사 | 남기는 칸 |
| --- | --- | --- | --- | --- | --- |
| approve | DRAFT | APPROVED | 관리자 | 비활성 업체·품목이 들면 409 `INACTIVE_REFERENCE` | approved\_by, approved\_at |
| order | APPROVED | ORDERED | 둘 다 | 없음 | ordered\_at |
| cancel | DRAFT, APPROVED, ORDERED | CANCELLED | 둘 다 | 연결된 RECEIPT 행이 있으면 409 `CANNOT_CANCEL_RECEIVED` | cancelled\_at |

동시에 눌러도 한 번만 반영되는 방법은 발주서 행 잠금이다(잠근 뒤 현재 상태를 읽고 바꾼다). 응답은 바뀐 발주서(`GET /purchase-orders/{id}`와 같은 모양)다.

### 5) 발주 추천 조회: GET /recommendations

계산은 이 요청이 올 때 서버가 한다(계산 결과를 저장하지 않는다. 임시 확정, ERD와 같다). 예시는 일평균 10, 리드타임 5, 안전재고 20, 현재고 50인 품목(S1)이다.

```json
{
  "data": {
    "items": [{
      "product_id": 12, "product_name": "물티슈 10롤", "supplier_id": 3,
      "current_stock": 50, "in_transit": 0, "available": 50,
      "avg_daily_sales": 10, "lead_time_days": 5, "safety_stock": 20,
      "reorder_point": 70, "recommended_quantity": 160,
      "reason": "최근 30일 하루 평균 10개가 팔렸고 리드타임은 5일입니다. 리드타임 동안 50개가 필요하고 안전재고 20개를 더하면 70개입니다. 지금 가용재고는 50개라서 발주를 추천합니다."
    }],
    "excluded": [
      { "product_id": 15, "product_name": "수건 5입", "code": "NO_SALES_30D", "message": "최근 30일 판매 없음" }
    ]
  }
}
```

`excluded`에는 추천을 계산할 수 없는 품목과 이유 코드를 담는다: `MISSING_INFO`(S7, 기본 공급업체가 비활성, 메시지 "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요"), `INSUFFICIENT_DATA`(S6, (오늘 − 첫 입출고 날짜) < 14일), `NO_SALES_30D`(S5). 여러 사유가 겹치면 MISSING\_INFO → INSUFFICIENT\_DATA → NO\_SALES\_30D 순서로 첫 번째 하나만 낸다(S14). 비활성 품목은 추천 목록에 나오지 않는다.

`avg_daily_sales`와 `reorder_point`는 소수 그대로 계산하고, `recommended_quantity`만 올림한 정수다. 예) 30일 판매 7, 리드타임 5, 안전재고 2, 가용재고 0 → 일평균 0.233…, 재주문점 3.17, 추천 수량 6.43 → 7(S12). 화면과 이유 문구에서는 일평균을 소수 첫째 자리까지 보여준다. 이유 문구는 AX 설계 문서의 문장 틀에 계산 숫자만 끼워 넣는다(확정, LLM은 C1).

### 6) 추천으로 초안 만들기: POST /recommendations/drafts

```json
{
  "items": [
    { "product_id": 12, "quantity": 160 },
    { "product_id": 18, "quantity": 200 }
  ]
}
```

서버는 받은 품목의 추천을 다시 계산해 `recommended_quantity`와 `recommendation_reason`을 저장하고(화면이 보낸 값을 믿지 않는다), `quantity`는 사용자가 고친 값 그대로 둔다. 그래야 나중에 "추천 대비 수정 비율"을 잴 수 있다. 품목을 공급업체별로 묶어 공급업체당 DRAFT 발주서 1장에 담는다(S9). 그 공급업체의 DRAFT가 이미 있으면 새로 만들지 않고 품목만 추가한다(S10). 응답은 품목이 들어간 발주서 목록이고, 각 발주서에 `created: true`(새로 만든 것) 또는 `false`(기존 초안에 추가한 것)를 붙인다. 이미 그 초안에 같은 품목이 있으면 409 `DUPLICATE_ITEM`으로 막는다(임시 확정). 비활성 품목이나 기본 공급업체가 비활성인 품목은 초안을 만들 수 없다(409 `INACTIVE_REFERENCE`).

## 권한과 오류 코드

### 역할별 허용

권한은 인터뷰 전이라 최소한으로 가정했다. 확정된 것은 승인만 관리자라는 점(R5)뿐이고, 나머지는 임시 확정이다.

| 동작 | 관리자 | 담당자 | 상태 |
| --- | --- | --- | --- |
| 직원 계정 생성·역할 변경·비활성 | 허용 | 막힘 | 임시 확정 |
| 공급업체·품목 등록·수정·비활성 | 허용 | 허용 | 임시 확정 |
| 입고·출고·재고 조정·정정 등록 | 허용 | 허용 | 임시 확정 |
| 발주 초안 생성·수정, 추천으로 초안 만들기 | 허용 | 허용 | 임시 확정 |
| 발주 승인(approve) | 허용 | 막힘 | 확정 |
| 발주함 표시(order)·입고·취소 | 허용 | 허용 | 임시 확정 |
| 모든 조회(재고·이력·추천·대시보드) | 허용 | 허용 | 임시 확정 |

권한 검사는 경로마다 서버에서 한다. 화면이 버튼을 숨기는 것은 편의일 뿐 보안이 아니다.

### 오류 코드

오류 응답의 `code`는 아래 중 하나다. 프론트는 code로 분기하고 message는 그대로 보여준다.

| code | HTTP | 언제 | 관련 규칙·시나리오 |
| --- | --- | --- | --- |
| UNAUTHENTICATED | 401 | 토큰이 없거나 만료됨 | 인증 |
| FORBIDDEN\_ROLE | 403 | 역할이 허용되지 않음(예: 담당자의 승인) | R5, S11 |
| NOT\_FOUND | 404 | 없는 id이거나 다른 회사의 id | R1, S8 |
| VALIDATION\_ERROR | 422 | 필수 칸 비어 있음, 수량이 1 미만·정수 아님, 리드타임이 음수, SALE인데 채널 없음, 조정·정정인데 사유 없음, 정정의 정정 | R7, R10 |
| INSUFFICIENT\_STOCK | 409 | 빼고 남는 재고가 0 미만이 되는 출고·감소 조정·정정 | R3 |
| OVER\_RECEIPT | 409 | 누적 입고량이 발주 수량을 넘음 | 확정 정책 |
| CORRECTION\_EXCEEDS | 409 | 한 이력에 대한 정정 수량 합계가 원래 수량을 넘음 | 정정 이력(A1) |
| INVALID\_STATUS | 409 | 현재 발주 상태에서 할 수 없는 동작(초안이 아닌데 수정, 승인 전 발주, ORDERED가 아닌 발주의 입고 정정 등) | R5 |
| CANNOT\_CANCEL\_RECEIVED | 409 | 입고 이력이 있는 발주 취소 | 확정 정책 |
| DUPLICATE\_ITEM | 409 | 같은 발주서(초안)에 같은 품목을 두 줄 넣거나 다시 넣음 | S10 |
| DUPLICATE\_DRAFT | 409 | 이미 DRAFT가 있는 공급업체에 새 발주서를 만듦. details에 기존 발주서 id·발주번호(#33) | S10 |
| INACTIVE\_REFERENCE | 409 | 비활성 공급업체를 품목의 기본 공급업체로 고르거나(등록·수정, #26), 비활성 공급업체·품목을 새 발주서 작성·품목 추가·추천 초안 생성에 쓰거나, 비활성이 든 DRAFT를 승인. 출고·조정·정정, 이미 ORDERED인 발주의 입고, 발주 없는 직접 입고에는 내지 않는다 | 비활성 범위(A3) |
| EMAIL\_TAKEN | 409 | 이미 쓰는 이메일로 계정 생성 | F1 |
| LAST\_ADMIN | 409 | 회사의 마지막 활성 관리자를 담당자로 바꾸거나 비활성으로 바꿈(자기 자신 포함) | F1 |
| DUPLICATE\_NAME | 409 | 같은 회사에 같은 이름의 공급업체를 등록하거나 그 이름으로 바꿈(앞뒤 공백 제거 후 비교, 다른 회사는 허용) | F2 |
| DUPLICATE\_SKU | 409 | 같은 회사에 같은 SKU의 품목을 등록하거나 그 SKU로 바꿈(공백 제거·대문자로 비교, 다른 회사는 허용) | F3 |

에러가 날 때 어느 칸이 문제인지는 `details`에 칸 이름과 사유로 담는다(VALIDATION\_ERROR). 401과 403은 왜 실패했는지 최소한만 알려준다.

## 시나리오 S1\~S14와 API 대응, 열린 질문

정답 시나리오는 모두 위 엔드포인트로 재현할 수 있다. 구현 때 이 표가 자동 테스트의 뼈대가 된다.

| 번호 | 부르는 API | 기대 결과 |
| --- | --- | --- |
| S1 | GET /recommendations | items에 포함, recommended\_quantity 160 |
| S2 | GET /recommendations | items에 없음 |
| S3 | GET /recommendations | ORDERED 발주의 미입고 수량이 in\_transit에 들어가 추천 없음 |
| S4 | GET /recommendations | CANCELLED는 in\_transit 0, 추천 160 |
| S5 | GET /recommendations | excluded: NO\_SALES\_30D |
| S6 | GET /recommendations | excluded: INSUFFICIENT\_DATA |
| S7 | GET /recommendations | 기본 공급업체가 비활성인 품목은 excluded: MISSING\_INFO |
| S8 | 회사 X 토큰으로 GET /recommendations·GET /products/{Y의 id} | Y의 품목은 목록에 없고 상세는 404 |
| S9 | POST /recommendations/drafts | DRAFT 1장, 품목 2줄 |
| S10 | POST /recommendations/drafts(두 번) | 두 번째는 created: false, 새 발주서 없음 |
| S11 | 담당자 토큰으로 POST /purchase-orders/{id}/approve | 403 FORBIDDEN\_ROLE |
| S12 | GET /recommendations | 30일 판매 7, 리드타임 5, 안전재고 2, 가용재고 0 → recommended\_quantity 7(6.43 올림) (임시 확정) |
| S13 | SALE 100 등록 → POST /inventory-movements/{그 SALE id}/corrections(90) → GET /recommendations | 30일 판매 합계 10으로 계산 (임시 확정) |
| S14 | GET /recommendations | 첫 기록 10일 전, 30일 판매 0 → excluded: INSUFFICIENT\_DATA(NO\_SALES\_30D 아님) (임시 확정) |

### 열린 질문

아래는 사용자가 "일단 네 판단대로"라고 맡겨 11월 3일에 임시 확정한 것들이다. 나중에 바꿀 수 있다.

- 역할은 관리자·담당자 두 개로 시작한다. 읽기 전용 역할(창고 담당 등)은 인터뷰 후 필요하면 추가한다(임시 확정).
- 비활성이 된 품목이 들어 있는 DRAFT 발주서는 그대로 두되 승인 시점에 INACTIVE\_REFERENCE로 막는다(임시 확정).
- 토큰은 httpOnly 쿠키로 주고받는다(임시 확정). 쿠키의 SameSite=Lax·Secure 설정과 Next.js rewrites 방식은 확정이다(설계 원칙 표). 만료 시간은 구현할 때 정한다.
- 목록의 페이지 크기 기본값은 20, 정렬은 최신순이다(임시 확정).
- 작성자(누가 이력을 등록·승인했는지)를 응답에 내려줄 칸 이름은 ERD의 칸에 맞춘다.

추천 계산 시점은 "요청이 올 때 계산"으로 임시 확정했다. 최근 30일은 오늘 포함 30일, 데이터 부족은 품목의 첫 입출고 기록일부터 14일 미만으로 확정했다(ERD 문서와 같다). 다음 단계는 아키텍처 문서다.
