# 06. 시스템 설계 (System Design)

> 2026-11-03 기준 초안. 검토 전이며, 구현하면서 바뀔 수 있습니다.

## 문서 목록

| 문서 | 내용 |
|---|---|
| [erd.md](./erd.md) | 표 9개(업무 7개 + 멱등 키 + 발주서 변경 이력), 컬럼, 관계, 업무 규칙(R1~R10) 대응, 시나리오 S1~S14 점검 |
| [api-design.md](./api-design.md) | REST API 32개, 권한, 오류 코드, 핵심 API 상세 |
| [architecture.md](./architecture.md) | 기술 스택, 구성도, 폴더 구조, 추천 계산 함수, 배포·운영, 주차별 계획 |

읽는 순서: ERD → API → 아키텍처.

## 핵심 설계 요약

- 표 9개: companies, users, suppliers, products, purchase_orders, purchase_order_items, inventory_movements, idempotency_keys(멱등 키, #190), po_change_log(발주서 변경 이력, #181)
- 재고는 컬럼으로 저장하지 않고 `inventory_movements`의 합계로 계산한다.
- 모든 업무 표에 `company_id`를 둔다. 회사 정보는 토큰에서만 가져온다.
- 마이너스 재고는 서버 트랜잭션과 행 잠금으로 막는다.
- 발주 상태: DRAFT → APPROVED → ORDERED → RECEIVED (관리자만 승인)
- 추천: 일평균 판매 = 최근 30일 SALE 합계 ÷ 30, 발주점 = 일평균 × 리드타임 + 안전재고, 가용재고 = 재고 + 입고 전 ORDERED 수량

## 결정 현황

### 확정 (사용자)

- 입출고 이력은 수정·삭제할 수 없다. 실수는 정정(CORRECTION) 이력으로 바로잡는다(아래 A1).
- "데이터 부족" = 상품의 첫 입출고 기록 후 14일 미만 (AX 문서 기준)
- 최근 30일은 오늘을 포함한다 (오늘−29 ~ 오늘).
- 리드타임은 공급처에 저장, 상품마다 기본 공급처 필수, 출고 유형은 SALE/DISPOSAL/OTHER_OUT (SALE만 일평균에 반영), 재고 실사 차이는 사유가 필수인 ADJUSTMENT.

설계 리뷰 결정 (2026-11-03, 사용자 확정)

- A1 실수 정정 이력: `movement_type`에 CORRECTION 추가, `reverses_movement_id`로 원래 이력을 가리킨다. 사유 필수, direction은 원래의 반대, 정정의 정정 불가, 정정 수량 합계 ≤ 원래 수량. 발주 입고 정정은 ORDERED일 때만(RECEIVED는 불가, 한계). 30일 판매·누적 입고량에서 정정 수량을 뺀다. ADJUSTMENT는 실사 차이 전용.
- A2 S7 재정의: 기본 공급업체가 비활성이면 추천에서 제외(MISSING_INFO, "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요").
- A3 비활성 범위: 공급업체·품목은 삭제 없이 항상 비활성. 비활성은 새 발주(새 발주서·품목 추가·추천·초안)에만 안 나오고, 비활성이 든 DRAFT는 승인 때 INACTIVE_REFERENCE. 출고·조정·정정, ORDERED 발주의 입고, 직접 입고(반품 등)도 허용.
- A4 소수와 올림: 일평균·재주문점·비교는 소수 그대로, 최종 추천 수량만 올림(ceil). 일평균 표시는 소수 첫째 자리까지.
- A5 제외 사유 우선순위: MISSING_INFO → INSUFFICIENT_DATA → NO_SALES_30D 중 첫 번째 하나만. 데이터 부족 = (오늘 − 첫 입출고 날짜) < 14일. 계산 함수와 추천 service는 today를 인자로 받는다.
- A6 쿠키 인증 보안: 브라우저는 Next.js 주소로만 요청하고 Next.js가 `/api/*`를 FastAPI로 전달(rewrites, CORS 불필요). 쿠키는 httpOnly, SameSite=Lax, 배포 환경에서 Secure. 상태 변경은 POST/PATCH만, GET은 읽기만.

### 임시 확정 (위임: 일단 작성자 판단)

- 추천은 요청 시점에 계산하고 저장하지 않는다. 재고 캐시 표는 두지 않는다.
- 스택: FastAPI + PostgreSQL + Next.js (SQLAlchemy, Alembic, Docker, GitHub Actions)
- 역할 2개(관리자, 담당자), 토큰은 httpOnly 쿠키, 목록은 20개씩 최신순
- 임시 비밀번호 첫 로그인 변경은 MVP 이후로 미룬다.
- 비활성 상품이 든 DRAFT 발주는 두되, 승인할 때 INACTIVE_REFERENCE로 막는다.
- 정답 시나리오 S12(소수 올림), S13(판매 정정), S14(사유 겹침)를 추가한다.
- 장기재고 = 60일 넘게 순판매 없음(`DEAD_STOCK_DAYS`, #37), 과잉재고 = 현재고 ≥ 일평균 × 90일(`OVERSTOCK_DAYS`, #76). 둘 다 인터뷰 후 재검토
- 부족 = 추천 대상(가용재고 ≤ 재주문점)과 같은 계산 하나로 판정한다(#76)

### 미정

- 클라우드(GCP/AWS)와 월 비용 상한: 7주차 배포 전 결정
- 보충 주기 14일: 인터뷰와 측정 후
- 권한표: 인터뷰 후
