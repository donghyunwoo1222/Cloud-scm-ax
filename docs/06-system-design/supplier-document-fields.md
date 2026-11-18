# 공급업체용 발주서 문서: 공개/내부 칸 분류표 (#281)

발주서는 화면(인쇄·PDF 저장), 엑셀, 메일 첨부 PDF, 메일 본문으로 공급업체에 전달된다. 값은 모두 `po_document.build_document` 한 곳에서 만들고, 각 출력은 그 값에서 칸을 하나씩 골라 쓴다(허용 목록 방식, 문서 전체를 돌며 숨기는 방식이 아님).

- 화면: `frontend/app/(app)/purchase-orders/[id]/document/page.tsx` (문서 JSON `GET /purchase-orders/{id}/document`)
- 엑셀: `po_document.build_xlsx`
- PDF(메일 첨부): `po_document.render_pdf` → `build_pdf`
- 메일 본문: `po_mail.subject_of`(제목), `default_intro`(앞머리 기본 문단), `fixed_html`·`fixed_text`(머리 표·품목·조건·글자 도장·승인 줄, 칸 목록은 `party_rows`), 머리글은 `build_message`

기준: origin/main `0ddf53f` (#300 머지 뒤), 메일 본문은 #264 PR3 반영. 줄 번호 대신 함수 이름을 쓴다(#285).

## 1. 문서 칸 (build_document 결과)

○ = 나감, - = 안 나감.

| 칸 | 어디서 나오는지 | 화면 | 엑셀 | PDF | 메일 본문 | 분류 | 비고 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `po_number` | `build_document` ← 발주서 | ○ | ○ (시트 이름 포함) | ○ | ○ (제목·본문) | 공개 | 첨부 파일 이름에도 쓰임 |
| `order_date` | `build_document` (작성일, 서울 기준) | ○ | ○ | ○ | ○ (제목·본문) | 공개 | |
| `status` | `build_document` ← 발주서 상태 | - (메일 버튼 표시 조건에만 씀) | - | - | - | 내부 전용 | 종이에는 안 그림. 문서 JSON 에만 있다 |
| `supplier.name` | `build_document` ← 공급업체 | ○ | ○ | ○ | ○ (앞머리·머리 표) | 공개 | |
| `supplier.contact_name` | 〃 | ○ | ○ | ○ | ○ (앞머리·머리 표) | 공개 | |
| `supplier.phone` | 〃 | ○ | ○ | ○ | ○ (머리 표 수신처) | 공개 | |
| `supplier.email` | 〃 | ○ | ○ | ○ | ○ (머리 표 수신처, To 머리글) | 공개 | |
| `buyer.name` | `build_document` ← 회사 | ○ | ○ | ○ | ○ (제목·앞머리·머리 표·도장 글자, From 이름) | 공개 | |
| `buyer.business_number` | 〃 (`fmt_business_number`) | ○ | ○ | ○ | ○ (머리 표 발주처) | 공개 | |
| `buyer.representative` | 〃 | ○ | ○ | ○ | ○ (머리 표 발주처) | 공개 | |
| `buyer.phone` | 〃 | ○ | ○ | ○ | ○ (머리 표 발주처) | 공개 | |
| `buyer.address` | 〃 | ○ | ○ | ○ | ○ (머리 표 발주처) | 공개 | |
| `buyer.author_name` | `build_document` ← 작성자 이름 | ○ | ○ | ○ | ○ (머리 표 작성자, "답장하시면 ○○ 담당자에게") | 공개 (확정) | 담당자가 보이고 Reply-To 와 같은 사람이어야 공급업체가 누구에게 연락할지 안다 |
| `lines[]` (no·product_name·product_sku·unit·quantity·unit_price·amount·note) | `build_document` ← `po_service.build_out` 에서 칸을 골라 씀 | ○ | ○ | ○ | ○ | 공개 | note 는 박스 환산(예: 1박스=10개) |
| `supply_total`·`vat`·`total`·`total_korean` | `build_document` (`vat_of`, `korean_amount`) | ○ | ○ | ○ | ○ | 공개 | |
| `due_date` | `build_document` ← 발주서 | ○ | ○ | ○ | ○ | 공개 | |
| `delivery_address` | 〃 (비면 회사 주소) | ○ | ○ | ○ | ○ | 공개 | |
| `payment_terms` | 〃 | ○ | ○ | ○ | ○ | 공개 | |
| `memo` | 〃 | ○ ("4) 기타") | ○ | ○ | ○ ("기타") | 공개 | 공급업체에 전달되는 칸이다(#281 결정). 작성·수정 화면 라벨: "기타 요청사항 (공급업체에 전달됩니다)" |
| `approval.approver_name`·`approved_at` | `build_document` (`user_names`, `seoul_time`) | ○ | ○ | ○ | ○ (승인 줄, 비면 "-") | 공개 | #263 결정 |
| `approval.company_name`·`stamp` | `build_document` (`stamp_of`) | ○ | - | ○ (도장, 상호가 바뀌었으면 "승인 시점 상호") | ○ (글자 도장 "상호 (인)", 상호가 바뀌었으면 "승인 시점 상호"; `stamp` 의 lines·ratio 는 안 씀) | 공개 | 메일 본문 도장은 그림이 아니라 글자(이미지·SVG 차단 대비, #264 PR3). 엑셀 도장은 없음 |

## 2. 문서에 넣지 않는 내부 전용 정보

아래는 엑셀·PDF·메일 본문·문서 JSON 어디에도 나가면 안 된다.

| 정보 | 있는 곳 | 비고 |
| --- | --- | --- |
| 추천 사유 `recommendation_reason`, 추천 수량 `recommended_quantity` | 발주 줄, `po_service.build_out` 응답 | `build_document` 가 줄 칸을 골라 쓰므로 안 들어간다 |
| 변경 이력 내용 | `po_change_log` | `build_document` 가 읽지 않는다 |
| 메일 발송 이력 `emailed_at`·`emailed_to`·`emailed_by` | 발주서 | 메일 미리보기 응답(`build_preview`, 로그인한 직원용)에는 있다. 공급업체 출력에는 없다 |
| 내부 id (회사·발주서·사용자·업체·품목·줄 id, `created_by`·`approved_by` 번호) | 각 표 | 문서에 필요 없다 |
| 멱등 키 | `idempotency_keys` | |
| 보낸 사용자 로그인 이메일 | 사용자 | 메일 머리글 Reply-To 에만 쓰인다(본문·문서·첨부에는 없음). Reply-To 유지는 3절에서 확정 |
| 원가·마진 등 내부 수익성 정보 | (현재 없음) | 앞으로 생겨도 공급업체 문서에는 넣지 않는다 |

## 3. 결정 (#264 PR3에서 확정)

- `buyer.author_name` 공개: **확정(공개)**. 화면·엑셀·PDF·메일 본문(머리 표 작성자)에 나간다. 이유: 공급업체가 문의할 담당자를 알아야 하고, 답장(Reply-To)도 그 담당자에게 간다.
- 메일 Reply-To(보낸 사용자 이메일) 유지: **확정(유지)**. `build_message` 머리글에만 쓰고 본문·첨부에는 넣지 않는다. 이유: 공급업체가 답장하면 담당자 메일함으로 가야 반자동 발송이 의미가 있다.
- PDF 파일 속성 비움: **확정(비움)**. PDF 는 제목·작성자를 넣지 않는다(`build_pdf`, `test_po_pdf.py` 가 검사). 이유: 파일 속성은 사용자가 보기 어려워 내부 정보가 새도 모른다. 엑셀 문서 속성의 작성자 기본값 "openpyxl" 은 내부 정보는 아니며 후속 정리 예정이다.

## 4. 규칙: 문서에 칸을 더할 때

`build_document` 결과에 칸을 더하거나 엑셀·PDF·메일 본문이 새 값을 쓰게 바꾸는 PR은, 먼저 이 표에 그 칸의 출처·출력별 노출·분류(공개/내부 전용/결정 대기)를 적는다. 그다음 `backend/tests/test_supplier_doc_leak.py` 의 `ALLOWED_KEYS` 에 더한다. 이 테스트는 문서 키가 허용 목록과 하나라도 다르면 실패하고, 내부 전용 값(추천 사유·변경 이력·발송 이력·로그인 이메일·내부 id)에 넣은 표식 글자가 문서 JSON·엑셀(모든 시트·문서 속성)·PDF 글자·메일 제목·본문 어디에든 나오면 실패한다. 내부 전용 칸을 새로 만들면 그 테스트의 표식 목록에도 더한다. 화면에서 CSS로 숨기는 것은 차단이 아니다: 외부 출력에는 공개 칸만 골라 넣는다.
