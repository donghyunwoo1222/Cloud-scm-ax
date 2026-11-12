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
| sku_id·sku_code | `sku_id`는 `products.id`이고 재고·입출고·발주·추천은 이 번호로만 연결한다. `sku_code`는 `products.sku`이고 검색·표시용이다. 옵션(color·size·spec)·group_code는 속성이며, `q` 검색은 품목명·SKU·group_code·옵션에 걸리고 `group_code` 파라미터는 정확 일치로 거른다(/products·/stock, #178) | 확정 |
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
| 자동화 회사 정보 | GET /company, PATCH /company | 우리 회사 정보(사업자번호·대표자·주소·연락처) 조회·수정. 경로·본문에 회사 번호가 없고 토큰의 회사만 쓴다 (#156) | 조회 둘 다, 수정 관리자 |
| F1 | GET /users, POST /users, PATCH /users/{id} | 직원 목록, 이메일·임시 비밀번호로 계정 생성, 역할·비활성 변경 | 관리자 |
| F2 공급업체 | GET /suppliers, POST /suppliers | 목록(비활성 제외·포함 선택), 등록(리드타임 0 이상 정수) | 둘 다 |
| F2 | GET /suppliers/{id}, PATCH /suppliers/{id} | 상세, 수정·비활성 | 둘 다 |
| F3 품목 | GET /products, POST /products | 목록(`default_supplier_id`로 기본 공급업체 필터), 등록(기본 공급업체 필수) | 둘 다 |
| F3 | GET /products/{id}, PATCH /products/{id} | 상세, 수정·비활성 | 둘 다 |
| F4 입출고 | POST /inventory-movements | 직접 입고, 출고(판매·폐기·기타), 재고 조정 등록. movement\_type으로 구분 | 둘 다 |
| F4 | POST /inventory-movements/{id}/corrections | 잘못 넣은 이력 {id}를 정정(CORRECTION 등록) | 둘 다 |
| F4 | GET /inventory-movements | 이력 조회(품목·유형(여러 개 가능)·기간 필터, 정렬: 입출고일순 또는 등록순) | 둘 다 |
| 자동화 판매 가져오기 | POST /sales-imports/inspect, POST /sales-imports/preview, POST /sales-imports | 주문 파일(CSV·.xlsx) 열 확인, 미리보기, SALE 이력 일괄 반영 (#154, MVP 이후) | 둘 다 |
| 자동화 품목·입고 가져오기 | POST /receipt-imports/inspect, POST /receipt-imports/preview, POST /receipt-imports | 입고·품목 파일로 새 품목 등록 + 직접 입고 일괄 반영 (#155, MVP 이후) | 둘 다 |
| F5 현재 재고 | GET /stock, GET /stock/{product\_id} | 품목별 현재고(이력 합계)와 안전재고. 발주 진행 중 수량(`in_transit`), 상태(`status`: 가용재고 ≤ 재주문점이면 SHORTAGE, 추천 제외 품목은 UNKNOWN + `status_reason`, 비활성은 null, 추천과 같은 계산, #76). `q`(최대 100자)는 공백을 다듬어 SKU·품목명 부분 일치 검색에 사용한다(대소문자 무시, `%`·`_`는 글자 그대로). `status`와 함께 주면 두 조건으로 거른 뒤 쪽을 나눈다. | 둘 다 |
| F5 재고 추이 | GET /stock/{product\_id}/trend | 서울 기준 오늘 포함 30일의 품목별 마감 재고와 입고 기록 (#126) | 둘 다 |
| F6 발주 | GET /purchase-orders, POST /purchase-orders | 목록(`supplier_id`·`status`·`receipt_due` 필터, `q` 발주번호 부분 검색), DRAFT 발주서 만들기(직접). 응답의 `has_receipts`는 전량 정정된 입고 이력도 포함한다. | 둘 다 |
| F6 | GET /purchase-orders/{id}, PATCH /purchase-orders/{id} | 상세, DRAFT 일 때만 품목·수량 수정 | 둘 다 |
| 자동화 발주서 문서 | GET /purchase-orders/{id}/document, GET /purchase-orders/{id}/document.xlsx | 승인 이후(APPROVED·ORDERED·RECEIVED) 발주서의 문서 값(수신처·발주처·품목표·금액·한글 금액·발주 조건)과 같은 값의 엑셀 파일 (#157) | 둘 다 |
| 자동화 메일 발송 | GET /purchase-orders/{id}/email, POST /purchase-orders/{id}/email | 메일 미리보기(받는 사람·답장 주소·제목·기본 앞머리·고정 본문·첨부 이름)와 발송(성공하면 APPROVED → ORDERED, 발송 기록 저장) (#158) | 둘 다 |
| F6 | POST /purchase-orders/{id}/approve | DRAFT → APPROVED | 관리자 |
| F6 | POST /purchase-orders/{id}/order | APPROVED → ORDERED(공급업체에 발주했음 표시) | 둘 다 |
| F6 | POST /purchase-orders/{id}/receipts | 발주 품목 입고(부분 가능). 이력 등록 + 상태 갱신을 한 번에 | 둘 다 |
| F6 | POST /purchase-orders/{id}/cancel | 입고 이력이 없는 발주만 취소 | 둘 다 |
| F7 대시보드 | GET /dashboard | 부족·과잉·장기재고·진행 중 발주·이번 달 입출고 요약. 입고 예정과 월 입출고는 각각 `incoming_by_unit`, `in_by_unit`, `out_by_unit`에 재고 단위별 합계를 반환한다. | 둘 다 |
| F8 발주 추천 | GET /recommendations | 현재 시점 추천 목록 계산·반환 | 둘 다 |
| F8 | POST /recommendations/drafts | 선택한 품목으로 공급업체별 DRAFT 발주서 생성·품목 추가 | 둘 다 |

합계 엔드포인트는 41개다(점검용 `GET /health` 제외, 2026-11-09 라우터 기준, 판매 가져오기 3개 포함, 발주서 문서 2개·메일 발송 2개 포함). 발주 상태 변경을 PATCH의 status 칸으로 하지 않고 동사 경로(approve, order, cancel)로 나눴다. 이렇게 하면 "승인은 관리자만", "취소는 입고 없을 때만" 같은 규칙을 경로 하나에 하나씩 붙일 수 있고, 상태를 건너뛰는 요청(승인 생략)이 경로에서부터 존재하지 않는다(R5).

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

### 2-1) 이력 조회: GET /inventory-movements

쿼리(모두 선택): `product_id`, `movement_type`, `date_from`, `date_to`, `sort`, 공통 `page`·`page_size`(기본 20, 최대 100).

- `movement_type`은 **여러 번** 보낼 수 있다. `movement_type=SALE&movement_type=DISPOSAL`이면 그 유형들 중 하나인 이력이 나온다(OR). 값이 하나면 예전과 같이 그 유형만. 같은 값을 두 번 보내도 한 번으로 센다. 값은 RECEIPT·SALE·DISPOSAL·OTHER\_OUT·ADJUSTMENT·CORRECTION 중 하나이고, 그 밖의 값은 하나만 섞여 있어도 422 `VALIDATION_ERROR`(예전에는 여러 번 보내면 오류 없이 마지막 값만 적용됐다)
- `sort`는 `date`(기본) 또는 `registered`. `date`는 입출고일 최신순(같은 날은 번호가 큰, 나중에 등록한 줄 먼저). `registered`는 등록 순서 최신순(`created_at`, 같은 시각이면 번호가 큰 줄 먼저)이라 **과거 날짜로 방금 등록한 줄도 맨 위**에 온다. 그 밖의 값은 422
- 기간은 양 끝 날짜를 포함하고, 시작일이 종료일보다 늦으면 422. 비활성 품목의 이력도 보인다. 우리 회사 이력만 나온다(다른 회사 번호로 걸러도 빈 목록)
- 응답은 `{"data": [...], "meta": {page, page_size, total}}`. 각 줄에 품목 `product_sku`·`product_name`, `purchase_order_item_id`(발주 입고면 값이 있다), 정정이면 `reverses_movement_id`가 들어 있다

예) 출고 등록 화면의 최근 출고 10건: `GET /inventory-movements?movement_type=SALE&movement_type=DISPOSAL&movement_type=OTHER_OUT&movement_type=ADJUSTMENT&sort=registered&page_size=10`

이력의 `product_unit`은 품목 재고 단위이고, `purchase_order_id`는 연결된 발주서가 있을 때만 값이 있다. `correctable_quantity`는 원본 수량에서 누적 정정을 뺀 값이며 정정 행은 null이다. `include_current_stock=true`를 주면 응답에 포함된 품목들의 `current_stock`을 함께 받는다.

발주서 응답(상세·목록·작성·수정·상태 변경·입고·추천 초안 공통)의 품목 줄 `items[]`에는 `product_sku`·`product_name`과 함께 품목 마스터의 현재 `unit`(예: "개")이 있다(#93).

### 박스 단위 발주 (#110, MVP 이후)

- 품목 등록·수정·조회에 선택 칸 `units_per_box`(박스 입수, 1~100만)와 `box_unit_cost`(박스당 구매 단가, 0~1억 원)를 추가한다. 두 값이 모두 있거나 모두 null이어야 한다. 설정한 뒤에는 하나만 수정할 수 있고, 둘 다 null을 보내면 해제한다.
- 수동 발주 작성·수정의 품목 줄은 기존 `{"product_id": 1, "quantity": 30, "unit_price": 1000}` 또는 박스 방식 `{"product_id": 1, "box_quantity": 3}`을 받는다. 두 방식은 한 발주서의 서로 다른 줄에서 함께 쓸 수 있다. 새 박스 줄은 품목의 박스 입수와 박스당 구매 단가를 복사한다. 기존 박스 줄은 DRAFT에서 박스 수를 고쳐도 당시 값으로 계산한다. 기존 화면이 그 줄을 재고 단위 방식으로 다시 보내면 수량이 당시 입수의 배수이고 `unit_price`가 그대로일 때만 반영한다.
- 발주 줄 응답의 `quantity`, `received_quantity`, `recommended_quantity`는 모두 재고 단위다. 박스 줄에는 발주 당시 `units_per_box`와 `box_unit_price`, 발주한 `box_quantity`를 담고, 재고 단위 줄에는 이 세 칸이 null이다. 모든 줄에 `line_total`(원)을 담는다. 박스 줄의 `unit_price`는 당시 품목의 재고 단위 구매 단가이고, 실제 발주 금액은 `box_quantity × box_unit_price`다. 재고 단위 줄의 금액은 `quantity × unit_price`다. 예를 들어 10개입 3박스, 박스당 10,005원은 `quantity: 30`, `line_total: 30015`다.
- 설정이 없는 품목에 박스 발주를 요청하거나, 박스 수를 환산한 재고 단위 수량이 기존 상한인 100만을 넘으면 422 `VALIDATION_ERROR`다.
- 발주단위 이름(#185): 품목 등록·수정에 선택 칸 `order_unit`(1~20자)을 받는다. 박스 설정이 있는데 비우면 "박스", 박스 설정 없이 보내면 422 `VALIDATION_ERROR`(field `order_unit`), 박스 설정을 해제하면 함께 비운다. 품목·추천·발주 줄 응답에 `order_unit`과 `unit_factor`(= `units_per_box`, 박스 설정이 없으면 기본단위·1)를 더한다. 발주 줄의 두 값은 발주 당시 스냅샷이다. 발주 요청의 품목 줄은 모르는 칸을 422로 거절하므로 `unit_factor`·`order_unit`을 보낼 수 없다.
- 최소 주문량(#194): 품목 등록·수정에 선택 칸 `min_order_units`(발주단위 수, 정수 1~1,000,000, null 이면 제한 없음)를 받고 품목 응답에 담는다. 발주 줄 응답의 `min_order_units`는 발주 당시 스냅샷이다. MOQ 미만 발주도 서버는 저장한다(화면이 확인을 받는다).

### 판매 가져오기 (#154, MVP 이후)

세 경로 모두 multipart로 `file`(.csv UTF-8·BOM·CP949, .xlsx 첫 시트, 5MB·5,000행 이하)을 매번 다시 받는다. 서버는 파일을 저장하지 않는다(무상태).

- `POST /sales-imports/inspect` (`file`, 선택 `status_col`): `headers`, `row_count`, `suggested`(머리글 이름으로 고른 열 번호 힌트), `status_values`(고른 상태 열의 값·개수, 50종 이하). 다른 열 값(수취인·주소 등)은 돌려주지 않는다.
- `POST /sales-imports/preview` (`file`, `options` JSON): 아무것도 쓰지 않는다. `options`는 `product_col`·`quantity_col`·`date_col`·`ref_col`(0부터, 서로 달라야 함), 선택 `status_col`+`statuses`, `option_col`, `sales_channel`, `exclude_problems`. 응답은 `apply_count`, `skipped`(사유별: `STATUS_NOT_SELECTED`·`ALREADY_IMPORTED`), `date_from`·`date_to`, `total_quantity`, `problem_count`, `problems`(앞 200건: `row` 파일 줄 번호, `reason`), `warnings`(한 SKU에 옵션 2종 이상).
- `POST /sales-imports` (201): 같은 입력 + `sales_channel` 필수. 품목을 번호순으로 잠근 뒤 다시 계산하고 `register_movement`로 SALE을 날짜순으로 쓴다(한 트랜잭션). 문제 행이 있고 `exclude_problems`가 아니면 409 `IMPORT_HAS_PROBLEMS`, 반영할 행이 없으면 409 `NOTHING_TO_IMPORT`, 동시에 같은 주문번호가 들어오면 409 `DUPLICATE_REF`.
- 문제 행 사유: `MISSING_SKU`, `INVALID_QUANTITY`(1~100만 정수), `INVALID_DATE`, `FUTURE_DATE`, `MISSING_REF`, `DUPLICATE_REF_IN_FILE`(뒤의 행만), `UNKNOWN_SKU`(다른 회사 SKU 포함), `INSUFFICIENT_STOCK`(품목마다 현재고에서 (날짜, 줄) 순으로 빼 음수가 되는 행. 문제 행은 재고를 쓰지 않은 것으로 친다).
- 파일 오류는 422 `FILE_TOO_LARGE`·`TOO_MANY_ROWS`·`INVALID_FILE`.

### 발주서 문서 (#157)

- `purchase_orders`에 선택 칸 `delivery_address`(납품장소), `payment_terms`(지불조건)가 생겼다(각 200자까지, 작성·수정·응답 공통). 작성할 때 `payment_terms`를 안 보내면 공급업체 기본값을 복사하고(추천 초안도 같다), 수정에서 `null`·빈 글자는 비운다.
- `GET /purchase-orders/{id}/document`: 화면과 엑셀이 같이 쓰는 값을 서버가 한 번 계산해 준다. `supplier`(수신처), `buyer`(발주처, 작성자 이름 포함), `lines`(No·품목명·SKU·단위·수량·단가·공급가액·비고), `supply_total`·`vat`·`total`·`total_korean`, `due_date`·`delivery_address`(비면 회사 주소)·`payment_terms`·`memo`. 회사 정보가 비어 있어도 만들어진다(해당 칸은 null).
- 금액: 단가는 부가세 별도. 공급가액 합계의 10%를 원 미만 버림으로 한 번만 계산하고(줄별 세액 없음, 예: 1,005원 → 100원), 합계 = 공급가액 + 부가세. 박스 발주 줄은 단위 "박스", 수량은 박스 수, 단가는 박스 단가이고 비고에 `1박스=24개`를 적는다. 한글 금액은 `일금 팔십삼만육천 원정` 식이며 금액 문서 관례대로 1도 읽는다(`일천`, `일십만`).
- `GET /purchase-orders/{id}/document.xlsx`: 같은 값의 엑셀 한 장(수량·단가·금액은 숫자 칸). 두 경로 모두 DRAFT·CANCELLED는 409 `INVALID_STATUS`, 다른 회사·없는 번호는 404. 읽기만 하므로 GET이다. 화면의 PDF는 브라우저 인쇄로 저장하고, 서버 PDF(`fpdf2`, 나눔고딕 동봉)는 메일 첨부(#158)에만 쓴다.

### 메일 반자동 발송 (#158)

- `GET /purchase-orders/{id}/email`: `to`(공급업체 이메일, 없으면 null), `supplier_id`, `reply_to`(지금 사용자 이메일), `subject`(`[회사명] 발주서 PO-… (발주일자)`), `intro`(기본 앞머리), `fixed_html`(품목표·합계·발주 조건, 서버가 escape), `attachments`(PDF·엑셀 이름), `status`, `emailed_at`·`emailed_to`, `mail_ready`(SMTP 설정 여부). APPROVED·ORDERED만, 그 밖은 409 `INVALID_STATUS`.
- `POST /purchase-orders/{id}/email` 본문 `{"intro": "앞머리(1~2000자)", "resend": false}`. 받는 사람·제목·고정 본문은 서버가 만들고 본문으로 바꿀 수 없다(모르는 칸 422). 발주서 행을 잠근 뒤 검사 → SMTP 발송 → 성공이면 APPROVED는 ORDERED(+`ordered_at`), `emailed_at`·`emailed_to`·`emailed_by`를 덮어쓰고 커밋한다. 응답은 발주서 하나.
- 오류: ORDERED인데 `resend`가 없으면 409 `ALREADY_ORDERED`(더블클릭 두 번째 요청도 여기서 막힌다), 공급업체 이메일 없음 409 `NO_SUPPLIER_EMAIL`, SMTP 설정 없음 503 `MAIL_NOT_CONFIGURED`, 메일 서버 거부·연결 실패 502 `MAIL_FAILED`(상태는 APPROVED 그대로), 메일은 나갔는데 저장 실패 500 `MAIL_SENT_NOT_SAVED`(다시 보내지 말고 확인 후 "주문 완료 표시"). 다른 회사 404. 권한은 "주문 완료 표시"와 같이 관리자·담당자 둘 다.
- 보내는 주소는 시스템 주소 하나(`SMTP_FROM`, 표시 이름은 회사명), `Reply-To`는 보낸 사용자. SMTP 계정은 환경 변수(`SMTP_HOST`·`SMTP_PORT`·`SMTP_USER`·`SMTP_PASSWORD`·`SMTP_FROM`·`SMTP_SECURITY`)로만 받는다. 로컬 Docker는 가짜 메일함 mailpit(http://localhost:8025)으로 보낸다.

### 회사 정보 (#156)

- `GET /company`: `id`·`name`·`business_number`·`representative`·`address`·`phone`(비어 있으면 null). `PATCH /company`: 보낸 칸만 바꾸고, `null`·빈 글자는 비운다(관리자만, 담당자 403). 회사명·`id`·`company_id`는 받지 않는다(무시).
- `business_number`는 `123-45-67890` 또는 `1234567890`을 받아 숫자 10자리로 저장한다. 그 밖(자리 수·하이픈 위치·글자)은 422 `VALIDATION_ERROR`.
- 공급업체에 선택 칸 `payment_terms`(200자까지, 지불조건 기본값)가 생겼다. 등록·수정·응답 공통.

### 품목·입고 가져오기 (#155)

파일 규칙과 세 단계는 판매 가져오기와 같다.

- `POST /receipt-imports/inspect` (`file`): `headers`, `row_count`, `suggested`.
- `POST /receipt-imports/preview` (`file`, `options` JSON): `options`는 `product_col`(필수), 선택 `quantity_col`(없으면 품목만 등록)·`date_col`(수량 열이 있으면 필수)·`ref_col`(없으면 `날짜|SKU|수량|n번째`로 번호를 만든다), 새 품목용 `name_col`·`unit_col`·`cost_col`·`safety_col`(비면 0), `supplier_col`(섞임 확인용), `default_supplier_id`, `exclude_problems`. 열은 서로 달라야 한다. 응답은 `new_product_count`·`new_products`(앞 200개), `apply_count`, `skipped`(`ALREADY_IMPORTED`·`PRODUCT_EXISTS`·`SAME_SKU_ABOVE`), `date_from`·`date_to`, `total_quantity`, `problem_count`, `problems`, `warnings`(새로 넣을 입고와 같은 날·같은 SKU의 RECEIPT가 이미 있으면 `sku`·`date`·`existing_quantity`. 막지 않고 알린다). `default_supplier_id`가 다른 회사면 404, 비활성이면 409. `supplier_col`을 골랐고 새 품목 행의 업체 값(빈 칸 제외)이 2곳 이상이면 422 `MULTIPLE_SUPPLIERS`(반영도 같음).
- `POST /receipt-imports` (201): 품목을 번호순으로 잠근 뒤 다시 계산하고, 새 품목을 만든 다음 RECEIPT를 날짜순으로 쓴다(한 트랜잭션). 새 품목이 있는데 공급업체가 없으면 422, 문제 행이 있으면 409 `IMPORT_HAS_PROBLEMS`, 할 일이 없으면 409 `NOTHING_TO_IMPORT`, 같은 SKU·번호가 동시에 들어오면 409 `IMPORT_CONFLICT`.
- 문제 행 사유: `MISSING_SKU`(비었거나 50자 초과), `INVALID_QUANTITY`, `INVALID_DATE`, `FUTURE_DATE`, `MISSING_REF`, `DUPLICATE_REF_IN_FILE`, `INVALID_PRODUCT_INFO`(새 SKU의 첫 행 값이 품목 등록 규칙에 어긋남, 그 SKU의 모든 행).

### 품목별 재고 추이 (#126)

`GET /stock/{product_id}/trend`는 품목 정보와 서울 기준 오늘을 포함한 30일의 `days`를 날짜 오름차순으로 반환한다. `closing_stock`은 기간 전 재고에 날짜별 입출고·조정·정정을 반영한 수량이다. 이력이 시작되기 전에는 null이며, 이후 변동 없는 날은 전날 값을 이어 간다. 오늘 값은 조회 시점까지의 수량이다.

`received_quantity`는 해당 날짜 입고에서 입고 정정을 뺀 수량이고, `reached_zero`는 직전 마감이 양수이고 해당 날짜의 마감 재고가 0일 때 true다. 정정은 원래 이력 날짜에 반영한다. 다른 회사 품목은 404다.

### 입고 납기 요약과 목록 필터 (#120)

대시보드 입고 대기 카드의 `purchase_orders.due_today`와 `purchase_orders.overdue`는 서울 기준으로 오늘이 납기인 발주함(ORDERED) 건수와 오늘보다 납기가 이른 발주함 건수다(#120). 부분 입고 발주도 한 건으로 센다.

발주 목록 `GET /purchase-orders?receipt_due=`에는 `TODAY`(오늘), `OVERDUE`(오늘보다 이전), `NEXT_7_DAYS`(내일~7일 뒤, 양 끝 포함), `UNSCHEDULED`(납기 미정)를 지정할 수 있다. 회사, 공급업체, 상태, 발주번호 검색 조건과 함께 발주함(ORDERED)인 줄을 먼저 거른 뒤 최신순으로 쪽을 나눈다. 발주함 이외의 상태를 함께 지정하면 빈 목록이고, 알 수 없는 납기 구간은 422다.

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

박스 발주 줄은 입고 요청에서 `quantity` 대신 `box_quantity`를 보낼 수 있다(#110). 예를 들어 `{"purchase_order_item_id": 1, "box_quantity": 2}`는 발주 당시 입수가 10이면 재고 단위 20개로 검사·저장한다. 초과 입고 오류의 `requested`·`remaining`도 재고 단위다. 낱개 입고는 기존 `quantity`를 쓰고 입고 정정도 재고 단위로 요청한다. 박스 입수가 없는 발주 줄에 `box_quantity`를 보내면 422다.

행 잠금 순서는 회사 → 발주서 → 품목이고, 여러 품목은 품목 번호 순으로 잠근다(교착 방지, PROGRESS.md의 행 잠금 순서).

입고일(`movement_date`)은 비우면 서울 오늘, 미래 날짜는 422(직접 입고와 같은 규칙). 한 요청의 모든 줄을 먼저 검사해 하나라도 넘치면 아무것도 저장하지 않는다(초과 메시지에 남은 수량, details에 `remaining`). 같은 줄을 두 번 보내면 422, 이 발주서에 없는 줄은 404. RECEIVED가 되면 `received_at`은 이 발주서 입고 이력 중 가장 늦은 입고일이다(erd.md). 응답은 201과 갱신된 발주서(`GET /purchase-orders/{id}`와 같은 모양)다(#35).

### 4) 발주 상태 변경: approve · order · cancel

세 경로 모두 요청 본문이 없다. 서버가 현재 상태를 보고 허용되는 한 단계만 바꾼다(DRAFT→APPROVED→ORDERED). 그 밖의 요청은 409 `INVALID_STATUS`, 담당자가 approve를 부르면 403 `FORBIDDEN_ROLE`(S11), 입고 이력이 있는 발주의 cancel은 409 `CANNOT_CANCEL_RECEIVED`이다(입고 후 전부 정정해 누적 입고량이 0이어도 RECEIPT 기록이 있으면 마찬가지, 임시 확정). 비활성 공급업체나 비활성 품목이 든 DRAFT를 approve하면 409 `INACTIVE_REFERENCE`이다. 상태 변경은 모두 한 번에 하나씩만 되도록, 서버가 먼저 발주서 행을 잠그고(SELECT … FOR UPDATE) 그 **뒤에** 현재 상태를 읽어 검사한 다음 바꾼다(두 명이 동시에 눌러도 한 번만 반영. 잠그기 전에 읽은 상태로 검사하면 두 요청이 모두 DRAFT를 보고 통과할 수 있다). "갱신 구문에 상태 조건을 넣는 방식"(UPDATE … WHERE status = …)은 쓰지 않는다. 입고·정정과 같은 행 잠금 방식으로 맞춰 잠금 순서 규칙 하나로 관리한다(#34, #71).

상태 변경이 다른 행을 함께 잠가야 하면 회사 → 발주서 → 품목 순서를 지킨다(PROGRESS.md의 행 잠금 순서).

허용 이동 표(#34). 여기 없는 이동은 모두 409 `INVALID_STATUS`다. RECEIVED는 입고(3))가 모든 품목이 다 찬 뒤에 정한다.

| 경로 | 출발 상태 | 도착 상태 | 역할 | 추가 검사 | 남기는 칸 |
| --- | --- | --- | --- | --- | --- |
| approve | DRAFT | APPROVED | 관리자 | 비활성 업체·품목이 들면 409 `INACTIVE_REFERENCE` | approved\_by, approved\_at |
| order | APPROVED | ORDERED | 둘 다 | 없음 | ordered\_at |
| cancel | DRAFT, APPROVED, ORDERED | CANCELLED | 둘 다 | 연결된 RECEIPT 행이 있으면 409 `CANNOT_CANCEL_RECEIVED` | cancelled\_at |

동시에 눌러도 한 번만 반영되는 방법은 위에 적은 발주서 행 잠금이다(동시 승인 8건 → 1건 성공, 테스트로 확인). 응답은 바뀐 발주서(`GET /purchase-orders/{id}`와 같은 모양)다.

### 5) 발주 추천 조회: GET /recommendations

계산은 이 요청이 올 때 서버가 한다(계산 결과를 저장하지 않는다. 임시 확정, ERD와 같다). 예시는 일평균 10, 리드타임 5, 안전재고 20, 현재고 50인 품목(S1)이다.

```json
{
  "data": {
    "items": [{
      "product_id": 12, "product_sku": "WT-10", "product_name": "물티슈 10롤", "supplier_id": 3, "supplier_name": "한빛유통",
      "current_stock": 50, "in_transit": 0, "available": 50,
      "avg_daily_sales": 10, "lead_time_days": 5, "safety_stock": 20,
      "reorder_point": 70, "recommended_quantity": 160,
      "reason": "최근 30일 하루 평균 10개가 팔렸고 리드타임은 5일입니다. 리드타임 동안 50개가 필요하고 안전재고 20개를 더하면 70개입니다. 지금 가용재고는 50개라서 발주를 추천합니다. 추천 수량은 160개입니다."
    }],
    "excluded": [
      { "product_id": 15, "product_sku": "TW-5", "product_name": "수건 5입", "code": "NO_SALES_30D", "message": "최근 30일 판매 없음" }
    ]
  }
}
```

`items`는 추천 대상(가용재고 ≤ 재주문점)만 최신 품목 먼저 담고, 충분한 품목은 어느 목록에도 넣지 않는다. 쪽 나누기는 하지 않는다(2026-11-04 사용자 결정, 모든 품목을 계산한 뒤 골라내므로). `avg_daily_sales`·`reorder_point`는 float다. `excluded`에는 추천을 계산할 수 없는 품목과 이유 코드를 담는다: `MISSING_INFO`(S7, 기본 공급업체가 비활성, 메시지 "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요"), `INSUFFICIENT_DATA`(S6, (오늘 − 첫 입출고 날짜) < 14일), `NO_SALES_30D`(S5). 여러 사유가 겹치면 MISSING\_INFO → INSUFFICIENT\_DATA → NO\_SALES\_30D 순서로 첫 번째 하나만 낸다(S14). 비활성 품목은 추천 목록에 나오지 않는다.

`avg_daily_sales`와 `reorder_point`는 소수 그대로 계산하고, `recommended_quantity`만 올림한 정수다. 예) 30일 판매 7, 리드타임 5, 안전재고 2, 가용재고 0 → 일평균 0.233…, 재주문점 3.17, 추천 수량 6.43 → 7(S12). 화면과 이유 문구에서는 일평균을 소수 첫째 자리까지 보여준다. 이유 문구는 AX 설계 문서의 문장 틀에 계산 숫자만 끼워 넣는다(확정, LLM은 C1).

박스 설정 품목의 추천에는 현재 `units_per_box`, `box_unit_cost`, `recommended_box_quantity`를 함께 반환한다(#110). 27개를 10개입으로 발주할 때 `recommended_quantity`는 27이고 `recommended_box_quantity`는 3이다. 박스 설정이 없는 품목은 추가 세 칸이 null이다. 모든 추천에는 `recommended_order_units`(발주단위 수, 27개 ÷ 10 → 3)와 `recommended_arrival_quantity`(도착 수량, 3 × 10 = 30)도 함께 반환한다(#187). 박스 설정이 없으면 환산계수 1이라 두 칸 모두 `recommended_quantity`와 같다.

최소 주문량(#194): `recommended_order_units` = max(발주단위 올림, `min_order_units`)이다. 추천 응답에 `min_order_units`와 `moq_applied`(최소 주문량 때문에 발주단위 수가 늘어났으면 true)를 더한다. 늘어난 경우 이유 문구 끝에 "최소 주문량 5BOX를 적용해 5BOX(500개)를 추천합니다. 부족분보다 340개 많습니다." 문장이 붙는다. `recommended_quantity`는 그대로 부족 수량이다. 수량을 비운 초안 만들기도 같은 값을 쓴다.

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

#40 구현에서 정한 것(2026-11-04): 한 요청의 `items`는 1~100개(넘으면 422), `quantity`는 1~100만, 추천 수량 칸을 보내면 422(서버만 정한다). 다시 계산했을 때 추천 대상이 아닌 품목(재고 충분·데이터 부족·30일 판매 없음)이 하나라도 있으면 409 `NOT_RECOMMENDED`로 전체를 거절한다(details에 품목별 `reason`: `ENOUGH_STOCK`·`INSUFFICIENT_DATA`·`NO_SALES_30D`). 같은 요청을 두 번 보내면 두 번째는 409 `DUPLICATE_ITEM`(details에 기존 초안 id·발주번호)이고 아무것도 바뀌지 않는다. 하나라도 막히면 앞 업체의 초안도 저장되지 않는다. 단가는 품목 단가, 납기는 오늘 + 리드타임, 응답은 201과 `data: [발주서 + created]`. 동시 요청은 회사 행을 잠가 한 줄로 세운다(부분 고유 인덱스는 마지막 방어).

박스 설정 품목의 초안 요청은 `product_id`만 보내면 서버가 다시 계산한 추천량을 박스 수로 올림한다(#110). 박스 수를 직접 정하려면 `box_quantity`를 보낸다. `quantity`를 보내면 기존처럼 재고 단위로 발주한다. 두 수량 칸에 명시적으로 `null`을 보내면 422다. 박스 설정이 없는 품목에는 `quantity`가 필요하다. 박스 환산 후 수량 상한과 박스 설정 검사는 수동 발주와 같다.

## 권한과 오류 코드

### 역할별 허용

권한은 인터뷰 전이라 최소한으로 가정했다. 확정된 것은 승인만 관리자라는 점(R5)뿐이고, 나머지는 임시 확정이다.

| 동작 | 관리자 | 담당자 | 상태 |
| --- | --- | --- | --- |
| 직원 계정 생성·역할 변경·비활성 | 허용 | 막힘 | 임시 확정 |
| 회사 정보 수정(조회는 둘 다) | 허용 | 막힘 | 임시 확정 |
| 공급업체·품목 등록·수정·비활성 | 허용 | 허용 | 임시 확정 |
| 입고·출고·재고 조정·정정 등록 | 허용 | 허용 | 임시 확정 |
| 발주 초안 생성·수정, 추천으로 초안 만들기 | 허용 | 허용 | 임시 확정 |
| 발주 승인(approve) | 허용 | 막힘 | 확정 |
| 발주함 표시(order)·입고·취소 | 허용 | 허용 | 임시 확정 |
| 발주서 문서·엑셀 보기(승인 이후) | 허용 | 허용 | 임시 확정 |
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
| NOT\_RECOMMENDED | 409 | 추천으로 초안 만들기에서 다시 계산해 보니 추천 대상이 아닌 품목이 있음(details에 품목·사유, #40) | F8 |
| DUPLICATE\_DRAFT | 409 | 이미 DRAFT가 있는 공급업체에 새 발주서를 만듦. details에 기존 발주서 id·발주번호(#33) | S10 |
| INACTIVE\_REFERENCE | 409 | 비활성 공급업체를 품목의 기본 공급업체로 고르거나(등록·수정, #26), 비활성 공급업체·품목을 새 발주서 작성·품목 추가·추천 초안 생성에 쓰거나, 비활성이 든 DRAFT를 승인. 출고·조정·정정, 이미 ORDERED인 발주의 입고, 발주 없는 직접 입고에는 내지 않는다 | 비활성 범위(A3) |
| EMAIL\_TAKEN | 409 | 이미 쓰는 이메일로 계정 생성 | F1 |
| LAST\_ADMIN | 409 | 회사의 마지막 활성 관리자를 담당자로 바꾸거나 비활성으로 바꿈(자기 자신 포함). 직원 변경은 회사 행을 잠근 뒤 대상 직원을 읽어 검사한다(#71) | F1 |
| DUPLICATE\_NAME | 409 | 같은 회사에 같은 이름의 공급업체를 등록하거나 그 이름으로 바꿈(앞뒤 공백 제거 후 비교, 다른 회사는 허용) | F2 |
| DUPLICATE\_SKU | 409 | 같은 회사에 같은 SKU의 품목을 등록하거나 그 SKU로 바꿈(공백 제거·대문자로 비교, 다른 회사는 허용) | F3 |
| HTTP\_ERROR | 400·405 등 | 위 코드에 해당하지 않는 프레임워크 오류(깨진 요청 본문, 허용하지 않는 메서드 등). 없는 경로는 NOT\_FOUND(`app/errors.py`) | 공통 |

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
