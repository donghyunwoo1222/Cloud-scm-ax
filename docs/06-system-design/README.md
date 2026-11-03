# 06. 시스템 설계 (System Design)

> 2026-11-03 기준 초안. 검토 전이며, 구현하면서 바뀔 수 있습니다.

## 문서 목록

| 문서 | 내용 |
|---|---|
| [erd.md](./erd.md) | 표 7개, 컬럼, 관계, 업무 규칙(R1~R10) 대응, 시나리오 S1~S11 점검 |
| [api-design.md](./api-design.md) | REST API 약 25개, 권한, 오류 코드, 핵심 API 상세 |
| [architecture.md](./architecture.md) | 기술 스택, 구성도, 폴더 구조, 추천 계산 함수, 배포·운영, 주차별 계획 |

읽는 순서: ERD → API → 아키텍처.

## 핵심 설계 요약

- 표 7개: companies, users, suppliers, products, purchase_orders, purchase_order_items, inventory_movements
- 재고는 컬럼으로 저장하지 않고 `inventory_movements`의 합계로 계산한다.
- 모든 업무 표에 `company_id`를 둔다. 회사 정보는 토큰에서만 가져온다.
- 마이너스 재고는 서버 트랜잭션과 행 잠금으로 막는다.
- 발주 상태: DRAFT → APPROVED → ORDERED → RECEIVED (관리자만 승인)
- 추천: 일평균 판매 = 최근 30일 SALE 합계 ÷ 30, 발주점 = 일평균 × 리드타임 + 안전재고, 가용재고 = 재고 + 입고 전 ORDERED 수량

## 결정 현황

### 확정 (사용자)

- 입출고 이력은 수정·삭제할 수 없다. 실수는 반대 방향 ADJUSTMENT 이력으로 바로잡는다.
- "데이터 부족" = 상품의 첫 입출고 기록 후 14일 미만 (AX 문서 기준)
- 최근 30일은 오늘을 포함한다 (오늘−29 ~ 오늘).
- 리드타임은 공급처에 저장, 상품마다 기본 공급처 필수, 출고 유형은 SALE/DISPOSAL/OTHER_OUT (SALE만 일평균에 반영), 재고 실사 차이는 사유가 필수인 ADJUSTMENT.

### 임시 확정 (위임: 일단 작성자 판단)

- 추천은 요청 시점에 계산하고 저장하지 않는다. 재고 캐시 표는 두지 않는다.
- 스택: FastAPI + PostgreSQL + Next.js (SQLAlchemy, Alembic, Docker, GitHub Actions)
- 역할 2개(관리자, 담당자), 토큰은 httpOnly 쿠키, 목록은 20개씩 최신순
- 임시 비밀번호 첫 로그인 변경은 MVP 이후로 미룬다.
- 비활성 상품이 든 DRAFT 발주는 두되, 승인할 때 INACTIVE_REFERENCE로 막는다.

### 미정

- 클라우드(GCP/AWS)와 월 비용 상한: 7주차 배포 전 결정
- 장기·과잉 재고 기준: F7 전
- 보충 주기 14일: 인터뷰와 측정 후
- 권한표: 인터뷰 후
