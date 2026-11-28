// 매입 세금계산서 수취 카드의 순수 함수와 모양 (#268). 서버 응답: backend/app/services/tax_invoices.py
// 내부 전용 값이다. 공급업체 문서 화면·문서 부품에서는 이 파일을 가져다 쓰지 않는다.
import type { PoStatus } from "./po.ts"; // 발주 상태 코드

// 계산서 한 장 (GET .../tax-invoices 의 items 한 칸)
export type TaxInvoice = {
  id: number; // 계산서 번호 (취소 요청에 쓴다)
  invoice_number: string; // 사용자가 적은 계산서 번호
  issue_date: string; // 발행일 (YYYY-MM-DD)
  supply_amount: number; // 공급가액(원)
  tax_amount: number; // 세액(원)
  total: number; // 공급가액 + 세액 (서버가 계산)
  tax_expected: number; // 공급가액의 10%(원 미만 버림). 다르면 안내만 한다
  memo: string | null; // 내부 메모
  created_by_name: string | null; // 기록한 사람
  created_at: string; // 기록 시각 (ISO)
  cancelled_at: string | null; // 취소 시각 (없으면 유효한 계산서)
  cancelled_by_name: string | null; // 취소한 사람
  cancel_reason: string | null; // 취소 사유
};

export type TaxStatus = "PENDING" | "MISSING" | "MATCHED" | "DIFFERENT"; // 서버 대조 결과 4가지

// 대조 요약 (취소한 계산서는 합계에서 빠져 있다)
export type TaxSummary = {
  received_goods_krw: number; // 입고 금액(원)
  supply_total: number; // 받은 공급가액 합(원)
  tax_total: number; // 세액 합(원)
  difference: number; // 계산서 − 입고 (+ 계산서가 많음, − 적음)
  status: TaxStatus; // 대조 결과
  line_count: number; // 입고된 품목 줄 수
};

export type TaxInvoiceView = { can_record: boolean; items: TaxInvoice[]; summary: TaxSummary }; // GET·POST·취소 응답 data

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`; // 쉼표 원 단위 글자

// 이 발주 상태에서 계산서 조회 API 를 부를지. 작성 중·승인됨은 계산서가 있을 수 없어 부르지 않는다
// 취소됨은 "기록한 뒤 취소한 발주"가 있을 수 있어 한 번 읽어 보고, 비어 있으면 카드를 그리지 않는다 (shouldShowCard)
// 예) "DRAFT" → false, "ORDERED" → true, "CANCELLED" → true
export const shouldFetchTaxInvoices = (status: PoStatus): boolean => status === "ORDERED" || status === "RECEIVED" || status === "CANCELLED";

// 카드를 그릴지: 발주함·입고 완료는 항상, 취소됨은 계산서가 1장 이상 남아 있을 때만
// 예) ("CANCELLED", 0) → false, ("CANCELLED", 2) → true, ("RECEIVED", 0) → true
export const shouldShowCard = (status: PoStatus, invoiceCount: number): boolean =>
  status === "ORDERED" || status === "RECEIVED" || (status === "CANCELLED" && invoiceCount > 0);

// 결과 배지 글자와 종류. PENDING 은 차이 숫자를 보이지 않는다 (입고 후 대조)
// 예) "MISSING" → { text: "미수취", kind: "danger" }
export function statusBadge(status: TaxStatus): { text: string; kind: "danger" | "ok" | "info" | "unknown" } {
  if (status === "PENDING") return { text: "입고 후 대조됩니다", kind: "unknown" };
  if (status === "MISSING") return { text: "미수취", kind: "danger" };
  if (status === "MATCHED") return { text: "일치", kind: "ok" };
  return { text: "차이 있음", kind: "danger" };
}

// 차이 문장 (DIFFERENT 일 때만). difference = 계산서 − 입고
// 예) +50,000 → "계산서가 입고 금액보다 50,000원 많음", −18,000 → "계산서가 입고 금액보다 18,000원 적음"
export function differenceText(summary: Pick<TaxSummary, "status" | "difference">): string | null {
  if (summary.status !== "DIFFERENT" || summary.difference === 0) return null;
  const side = summary.difference > 0 ? "많음" : "적음";
  return `계산서가 입고 금액보다 ${won(Math.abs(summary.difference))} ${side}`;
}

// "원 미만 처리 차이일 수 있어요" 안내를 보일지: 차이가 있고, 차이의 크기가 입고된 줄 수 미만일 때
// 공급업체가 줄마다 원 미만을 버리면 줄당 1원 미만씩 어긋날 수 있어서, 입고된 줄 수가 차이의 상한 눈금이다
// 예) 차이 2원, 입고 3줄 → true / 차이 3원, 3줄 → false / 차이 0 → false
export const showRoundingNote = (summary: Pick<TaxSummary, "status" | "difference" | "line_count">): boolean =>
  summary.status === "DIFFERENT" && summary.difference !== 0 && Math.abs(summary.difference) < summary.line_count;

export const ROUNDING_NOTE = "원 미만 처리 차이일 수 있어요"; // 위 조건일 때 작은 글자로
export const FREIGHT_NOTE = "운송비가 포함된 계산서는 차이로 보일 수 있어요. 품목 금액끼리만 비교합니다."; // 보조 문구

// 세액이 공급가액의 10% 와 다를 때의 안내 (저장은 막지 않는다). 같으면 null
// 예) 공급 10,000 · 세액 1,000 · 예상 1,000 → null / 세액 1,100 → "세액이 공급가액의 10%와 다릅니다(예상 1,000원)"
export const taxMismatchNote = (inv: Pick<TaxInvoice, "tax_amount" | "tax_expected">): string | null =>
  inv.tax_amount === inv.tax_expected ? null : `세액이 공급가액의 10%와 다릅니다(예상 ${won(inv.tax_expected)})`;

// 폼의 공급가액 → 세액 힌트 (공급가액의 10%, 원 미만 버림). 숫자가 아니면 null. 예) "10005" → 1000
export function vatHint(supply: string): number | null {
  const n = parseWon(supply);
  return n === null ? null : Math.floor(n / 10);
}

export const MAX_WON = 1_000_000_000_000; // 서버 BigWon 상한 (1조 원)

// 입력 글자 → 0 이상 정수 원. 쉼표는 허용, 소수·음수·빈 글자·글자 섞임은 null. 예) "1,000" → 1000, "1.5" → null, "-1" → null
export function parseWon(text: string): number | null {
  const clean = text.replace(/,/g, "").trim();
  if (!/^\d+$/.test(clean)) return null; // 숫자만 (부호·소수점 불가)
  const n = Number(clean);
  return Number.isSafeInteger(n) && n <= MAX_WON ? n : null;
}

// 기록 폼 검사: 문제가 있으면 문장, 없으면 null. today 는 서울 오늘(YYYY-MM-DD)
// 예) 번호 빈칸 → "계산서 번호를 입력해 주세요.", 발행일 > 오늘 → "발행일은 오늘 이후로 할 수 없어요."
export function formProblem(f: { number: string; date: string; supply: string; tax: string }, today: string): string | null {
  if (!f.number.trim()) return "계산서 번호를 입력해 주세요.";
  if (f.number.trim().length > 50) return "계산서 번호는 50자까지 입력할 수 있어요.";
  if (!f.date) return "발행일을 입력해 주세요.";
  if (today && f.date > today) return "발행일은 오늘 이후로 할 수 없어요."; // 같은 형식(YYYY-MM-DD)이라 글자 비교가 날짜 비교다
  if (parseWon(f.supply) === null) return "공급가액은 0 이상의 정수(원)로 입력해 주세요.";
  if (parseWon(f.tax) === null) return "세액은 0 이상의 정수(원)로 입력해 주세요.";
  return null;
}

// 서버 오류 → 사유별 문장. 서버 원문 대신 이 문장을 쓴다
export function taxInvoiceErrorText(error: unknown): string {
  const code = error && typeof error === "object" && "code" in error ? String((error as { code: unknown }).code) : "";
  const map: Record<string, string> = {
    DUPLICATE_TAX_INVOICE: "같은 공급업체에 같은 번호가 이미 있어요. 번호를 확인해 주세요.",
    INVALID_STATUS: "지금 상태의 발주서에는 세금계산서를 기록할 수 없어요. 화면을 새로 고쳐 주세요.",
    ALREADY_CANCELLED: "이미 취소된 세금계산서예요.",
    NOT_FOUND: "발주서나 세금계산서를 찾을 수 없어요.",
    VALIDATION_ERROR: "입력값을 확인해 주세요. 발행일은 오늘 이전이고, 금액은 0 이상의 정수여야 해요.",
    NETWORK_ERROR: "서버에 연결할 수 없어요. 잠시 뒤 다시 시도해 주세요.",
  };
  return map[code] ?? "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
}

// 취소한 계산서와 유효한 계산서를 나눈다 (서버는 최신순으로 준다)
export function splitInvoices(items: TaxInvoice[]): { active: TaxInvoice[]; cancelled: TaxInvoice[] } {
  return { active: items.filter((i) => !i.cancelled_at), cancelled: items.filter((i) => !!i.cancelled_at) };
}
