# 공급업체용 발주서 문서: 공개/내부 칸 분류표 (#281)

발주서는 화면(인쇄·PDF 저장), 엑셀, 메일 첨부 PDF, 메일 본문으로 공급업체에 전달된다. 값은 모두 `po_document.build_document` 한 곳에서 만들고, 각 출력은 그 값에서 칸을 하나씩 골라 쓴다(허용 목록 방식, 문서 전체를 돌며 숨기는 방식이 아님).

- 화면: `frontend/app/(app)/purchase-orders/[id]/document/page.tsx` (문서 JSON `GET /purchase-orders/{id}/document`)
- 엑셀: `po_document.build_xlsx`
- PDF(메일 첨부): `po_document.render_pdf` → `build_pdf`
- 메일 본문: `po_mail.subject_of`(제목), `default_intro`(앞머리 기본 문단), `fixed_html`·`fixed_text`(고정 부분), 머리글은 `build_message`

기준: origin/main `473cdc7` (#297 머지 뒤). 줄 번호 대신 함수 이름을 쓴다(#285).

## 1. 문서 칸 (build_document 결과)

○ = 나감, - = 안 나감.

| 칸 | 어디서 나오는지 | 화면 | 엑셀 | PDF | 메일 본문 | 분류 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `po_number` | `build_document` ← 발주서 | ○ | ○ (시트 이름 포함) | ○ | ○ (제목·본문) | 공개 | 첨부 파일 이름에도 쓰임 |
| `order_date` | `build_document` (작성일, 서울 기준) | ○ | ○ | ○ | ○ (제목·본문) | 공개 | |
| `status` | `build_document` ← 발주서 상태 | - (메일 버튼 표시 조건에만 씀) | - | - | - | 내부 전용 | 종이에는 안 그림. 문서 JSON 에만 있다 |
| `supplier.name` | `build_document` ← 공급업체 | ○ | ○ | ○ | ○ (앞머리) | 공개 | |
| `supplier.contact_name` | 〃 | ○ | ○ | ○ | ○ (앞머리) | 공개 | |
| `supplier.phone` | 〃 | ○ | ○ | ○ | - | 공개 | |
| `supplier.email` | 〃 | ○ | ○ | ○ | - (받는 주소 To 머리글) | 공개 | |
| `buyer.name` | `build_document` ← 회사 | ○ | ○ | ○ | ○ (제목·앞머리, From 이름) | 공개 | |
| `buyer.business_number` | 〃 (`fmt_business_number`) | ○ | ○ | ○ | - | 공개 | |
| `buyer.representative` | 〃 | ○ | ○ | ○ | - | 공개 | |
| `buyer.phone` | 〃 | ○ | ○ | ○ | - | 공개 | |
| `buyer.address` | 〃 | ○ | ○ | ○ | - | 공개 | |
| `buyer.author_name` | `build_document` ← 작성자 이름 | ○ | ○ | ○ | ○ ("답장하시면 ○○ 담당자에게") | **결정 대기** | 현재 공개. 승인자 이름만 공개할지 #281 열린 질문 |
| `lines[]` (no·product_name·product_sku·unit·quantity·unit_price·amount·note) | `build_document` ← `po_service.build_out` 에서 칸을 골라 씀 | ○ | ○ | ○ | ○ | 공개 | note 는 박스 환산(예: 1박스=10개) |
| `supply_total`·`vat`·`total`·`total_korean` | `build_document` (`vat_of`, `korean_amount`) | ○ | ○ | ○ | ○ | 공개 | |
| `due_date` | `build_document` ← 발주서 | ○ | ○ | ○ | ○ | 공개 | |
| `delivery_address` | 〃 (비면 회사 주소) | ○ | ○ | ○ | ○ | 공개 | |
| `payment_terms` | 〃 | ○ | ○ | ○ | ○ | 공개 | |
| `memo` | 〃 | ○ ("4) 기타") | ○ | ○ | ○ ("기타") | 공개 | 공급업체에 전달되는 칸이다(#281 결정). 작성·수정 화면 라벨: "기타 요청사항 (공급업체에 전달됩니다)" |
| `approval.approver_name`·`approved_at` | `build_document` (`user_names`, `seoul_time`) | ○ | ○ | ○ | - | 공개 | #263 결정 |
| `approval.company_name`·`stamp` | `build_document` (`stamp_of`) | ○ | - | ○ (도장, 상호가 바뀌었으면 "승인 시점 상호") | - | 공개 | 엑셀·메일 본문 도장은 #264 PR3 |

## 2. 문서에 넣지 않는 내부 전용 정보

아래는 엑셀·PDF·메일 본문·문서 JSON 어디에도 나가면 안 된다.

| 정보 | 있는 곳 | 비고 |
| --- | --- | --- |
| 추천 사유 `recommendation_reason`, 추천 수량 `recommended_quantity` | 발주 줄, `po_service.build_out` 응답 | `build_document` 가 줄 칸을 골라 쓰므로 안 들어간다 |
| 변경 이력 내용 | `po_change_log` | `build_document` 가 읽지 않는다 |
| 메일 발송 이력 `emailed_at`·`emailed_to`·`emailed_by` | 발주서 | 메일 미리보기 응답(`build_preview`, 로그인한 직원용)에는 있다. 공급업체 출력에는 없다 |
| 내부 id (회사·발주서·사용자·업체·품목·줄 id, `created_by`·`approved_by` 번호) | 각 표 | 문서에 필요 없다 |
| 멱등 키 | `idempotency_keys` | |
| 보낸 사용자 로그인 이메일 | 사용자 | 메일 머리글 Reply-To 에만 쓰인다(본문·문서·첨부에는 없음). 아래 결정 대기 참고 |
| 원가·마진 등 내부 수익성 정보 | (현재 없음) | 앞으로 생겨도 공급업체 문서에는 넣지 않는다 |

## 3. 결정 대기 (지금 동작 그대로 둠)

- `buyer.author_name` 공개 여부: 현재 화면·엑셀·PDF·메일 본문에 나간다.
- 메일 Reply-To(보낸 사용자 이메일) 공개 여부: 현재 머리글 Reply-To 에 들어간다(`build_message`).
- 파일 속성: PDF 는 제목·작성자를 넣지 않는다(`build_pdf`, `test_po_pdf.py` 가 검사). 엑셀 문서 속성은 openpyxl 기본값(작성자 "openpyxl")이며 내부 정보는 없다. 회사명으로 채울지는 미정.

## 4. 규칙: 문서에 칸을 더할 때

`build_document` 결과에 칸을 더하거나 엑셀·PDF·메일 본문이 새 값을 쓰게 바꾸는 PR은, 먼저 이 표에 그 칸의 출처·출력별 노출·분류(공개/내부 전용/결정 대기)를 적는다. 그다음 `backend/tests/test_supplier_doc_leak.py` 의 `ALLOWED_KEYS` 에 더한다. 이 테스트는 문서 키가 허용 목록과 하나라도 다르면 실패하고, 내부 전용 값(추천 사유·변경 이력·발송 이력·로그인 이메일·내부 id)에 넣은 표식 글자가 문서 JSON·엑셀(모든 시트·문서 속성)·PDF 글자·메일 제목·본문 어디에든 나오면 실패한다. 내부 전용 칸을 새로 만들면 그 테스트의 표식 목록에도 더한다. 화면에서 CSS로 숨기는 것은 차단이 아니다: 외부 출력에는 공개 칸만 골라 넣는다.
