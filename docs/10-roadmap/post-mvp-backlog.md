# MVP 이후 추가 구현사항 정리

docs/ 폴더의 기존 문서(00-proposal-summary, 01-benchmarking, 02-problem-definition, 03-planning, 99-glossary)에서 "MVP에서 제외되었거나 후순위·확장으로 언급된 항목"을 모은 목록입니다. 문서에 근거를 적을 수 없는 항목은 넣지 않았습니다. 우선순위나 일정은 이 문서에서 정하지 않습니다.

## 후순위·제외 항목

| 항목 | 한 줄 설명 | 왜 MVP에서 뺐는지 | 출처 문서(파일명과 섹션) | 분류 |
| --- | --- | --- | --- | --- |
| 제조업 확장 시나리오 (자재 소요량 기반 발주 + BOM 관리) | 제조업체도 쓸 수 있도록 BOM(자재 명세서) 관리와 자재 소요량 기반 발주 로직을 추가 | 대상 업종을 유통업 우선으로 좁히고 제조업은 확장 시나리오로 둠 | CLAUDE.md §10 열린 결정; docs/00-proposal-summary.md §확정된 결정; docs/02-problem-definition.md §대상과 전제, §Pain point(제조업 확장 시나리오 문단) | 업종 확장 |
| 판매 채널 API 연동 | 스마트스토어 등 실제 판매 채널과 API로 연동해 주문을 자동으로 가져오는 기능 | MVP는 출고 등록 시 채널명만 수기로 기록하는 수준으로 범위를 제한 | CLAUDE.md §3 MVP 범위; docs/00-proposal-summary.md §MVP 범위, §확정된 결정; docs/02-problem-definition.md §MVP 범위, §판매 채널 처리; docs/03-planning/service-planning.md §기획 범위와 전제 | 연동 |
| 고급 수요예측 기반 발주 추천 고도화 | 단순 재주문점 공식(일평균 판매량×리드타임+안전재고)을 넘어서는 수요 패턴 분석·예측 모델 | 처음에는 단순 공식으로 시작하고 사용자 테스트 후 개선하기로 함 | CLAUDE.md §3, §5; docs/00-proposal-summary.md §MVP 범위; docs/02-problem-definition.md §MVP 범위, §AX 적용 지점 | AX 확장 |
| 자연어 SCM 질의 | "다음 주 부족 예상 품목은?" 같은 자연어 질문에 LLM이 답하는 기능 | AX 선택 항목으로 분류되어 MVP 필수 범위 밖에 둠 | CLAUDE.md §3; docs/00-proposal-summary.md §MVP 범위; docs/02-problem-definition.md §MVP 범위, §AX 적용 지점(우선순위 3) | AX 확장 |
| 회계·급여·전사 ERP 기능 | 회계 처리, 급여 관리 등 전사적 자원관리(ERP) 범위의 기능 | 범위를 재고·입출고·발주·공급업체 관리로 한정하고 기존 ERP와 정면 경쟁을 피함 | CLAUDE.md §3; docs/00-proposal-summary.md §MVP 범위; docs/01-benchmarking/benchmarking-report.md §MVP 시사점과 출처; docs/02-problem-definition.md §MVP 범위 | 기능 확장 |
| 가격 투명성 개선(월 정액 가격 공개, 무료 체험) | 월 정액 요금을 공개하고 무료 체험 플랜을 제공하는 포지셔닝 | 벤치마킹에서 찾은 GAP이지만 이번 MVP가 풀지 않는 항목이라고 명시됨 | docs/01-benchmarking/benchmarking-report.md §GAP 분석, §제안서 연결: MVP와 GAP | 운영·품질 |
| 관리자 주간 요약 | 재고 이슈, 입출고, 발주 현황을 매주 자동으로 요약해 보여주는 기능 | AX 우선순위 4번이며, MVP에서는 1~2번(재고 부족 탐지, 적정 발주량 추천)만 먼저 구현 | docs/02-problem-definition.md §AX 적용 지점 | AX 확장 |
| 공급망 리스크 알림 | 납기 지연, 재고 부족, 공급업체 이슈를 미리 표시하는 알림 기능 | AX 우선순위 5번으로 "향후 고도화" 항목으로 명시됨 | docs/02-problem-definition.md §AX 적용 지점 | AX 확장 |
| 담당자 변경 시 입출고 이력·단가 추적 강화 | 담당자가 바뀌거나 자리를 비워도 입출고 이력과 단가 변동을 추적할 수 있게 하는 개선 | pain point #5는 근거 강도가 낮음으로 표시되어 MVP 이후로 미룸 | docs/02-problem-definition.md §Pain point(#5) | 운영·품질 |
| 초보자 진입장벽 완화(ERP 학습 부담·도입 비용 부담 해소) | 기존 ERP가 기능이 많아 처음 쓰기 어렵고 도입 비용이 부담된다는 문제를 더 폭넓게 해소하는 개선 | pain point #6은 MVP 이후로 미룸 | docs/02-problem-definition.md §Pain point(#6) | 운영·품질 |
| 재고 실사 기반 조정 입력 기능 | 주기적으로 실사한 재고와 시스템 재고가 다를 때 조정 내역을 입력하는 기능 | User journey 6단계(점검)는 MVP에서 이력 조회 수준까지만 지원하기로 범위를 제한함 | docs/02-problem-definition.md §User journey(6. 점검); docs/03-planning/service-planning.md §업무 흐름 | 기능 확장 |

## 열린 질문

docs/03-planning/service-planning.md §열린 질문과 다음 단계에 나온 질문 중, 구현 시점에 정해야 하는 항목입니다. 각 질문 옆은 해당 문서에 적힌 임시 가정입니다.

- 입고는 발주 없이도 등록할 수 있나요? (임시: 허용. 초기 재고와 직접 구매분을 위해 '직접 입고'로 구분)
- 부분 입고 후에 남은 수량을 취소할 수 있나요? (임시: 허용하지 않음, R4와 R6 충돌 방지)
- 대표가 직접 발주할 때 승인 단계를 생략할 수 있나요? (임시: MVP는 승인 단계 유지)
- 리드타임을 품목별로 저장할까, 공급업체별로 저장할까요? (임시: 품목별, 제안서 기준. 납기 이력은 공급업체별)
- 장기재고는 몇 개월 무출고를 기준으로 할까요? (임시: 정하지 않음, 인터뷰에서 확인)
- 실사 후 재고 차이는 어떻게 수정할까요? (임시: 입고·출고 이력에 "조정" 유형을 더하는 방법을 검토. 제안서 MVP 목록에는 없음)
