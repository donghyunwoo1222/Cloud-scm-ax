// 외화·원가 계산과 입력 검사 (순수 함수). 규칙 전문: docs/06-system-design/money-rules.md, 서버: backend/app/services/po_money.py
// 금액은 모두 BigInt(정수)로만 계산한다. float·Number 곱셈은 쓰지 않는다. 화면의 값은 항상 "예상"이고 저장값은 서버가 계산한다.

export type Currency = "KRW" | "USD" | "EUR" | "JPY" | "CNY" | "VND";

// 통화 → 이름, 환율 기준 단위(엔·동 100), 단가 소수 자릿수. 서버 po_money.CURRENCIES 와 같은 표
export const CURRENCIES: Record<Currency, { label: string; unitName: string; rateUnit: number; decimals: number }> = {
  KRW: { label: "KRW 원", unitName: "원", rateUnit: 1, decimals: 0 },
  USD: { label: "USD 달러", unitName: "달러", rateUnit: 1, decimals: 2 },
  EUR: { label: "EUR 유로", unitName: "유로", rateUnit: 1, decimals: 2 },
  JPY: { label: "JPY 엔", unitName: "엔", rateUnit: 100, decimals: 0 },
  CNY: { label: "CNY 위안", unitName: "위안", rateUnit: 1, decimals: 2 },
  VND: { label: "VND 동", unitName: "동", rateUnit: 100, decimals: 0 },
};
export const CURRENCY_CODES = Object.keys(CURRENCIES) as Currency[];
export const isCurrency = (v: unknown): v is Currency => typeof v === "string" && v in CURRENCIES;

// 운송비 조건 코드 → 화면 이름
export const FREIGHT_TERMS: Record<string, string> = {
  INCLUDED: "단가 포함(공급업체 부담)", BILLED: "별도 청구", COLLECT: "착불", EXW: "EXW", FOB: "FOB", CIF: "CIF", DDP: "DDP",
};
export const EXTRA_COST_SUGGESTIONS = ["통관 수수료", "관세", "보험료", "포장비"]; // 부대비용 이름 제안 (자유 입력도 된다)
export const MAX_EXTRA_COSTS = 20; // 부대비용 줄 상한 (서버와 같다)
export const MAX_SPECIAL_TERMS = 1000; // 특약 글자 상한

// 환율 칸 옆에 붙이는 문장. 예) JPY → "100엔당 원", USD → "1달러당 원"
export const rateUnitLabel = (c: Currency) => `${CURRENCIES[c].rateUnit}${CURRENCIES[c].unitName}당 원`;

// ── 입력 칸 필터: 허용되지 않는 글자가 들어오면 이전 값을 돌려준다 (붙여넣기 포함) ──
// 외화 단가: 정수부 8자리, 통화 소수 자릿수까지. 예) USD "0.5" 통과, "0.555" 이전 값, JPY "1.5" 이전 값
export function fxPriceInput(prev: string, next: string, currency: Currency): string {
  const d = CURRENCIES[currency].decimals;
  const ok = d === 0 ? /^\d{0,8}$/ : new RegExp(`^\\d{0,8}(\\.\\d{0,${d}})?$`);
  return ok.test(next) ? next : prev;
}
// 환율: 정수부 4자리, 소수 둘째 자리까지 (서버 상한 9,999.99)
export const rateInput = (prev: string, next: string) => (/^\d{0,4}(\.\d{0,2})?$/.test(next) ? next : prev);
// 원 단위 정수 칸 (운송비·부대비용): 13자리까지 (서버 상한 1조)
export const wonInput = (prev: string, next: string) => (/^\d{0,13}$/.test(next) ? next : prev);

// ── 글자 → 정수 ──
// "12.50" + 소수 2자리 → 1250n (센트 단위 정수). 통화 자릿수를 넘는 0 아닌 자릿수·형식 오류는 null. 끝자리 0 은 허용("5000.00" + 0자리 → 5000n)
export function toScaled(text: string, decimals: number): bigint | null {
  const m = /^(\d+)(?:\.(\d+))?$/.exec(text.trim());
  if (!m) return null;
  const frac = m[2] ?? "";
  if (/[1-9]/.test(frac.slice(decimals))) return null; // 자릿수 밖에 0 아닌 숫자가 있으면 거절
  return BigInt(m[1] + frac.slice(0, decimals).padEnd(decimals, "0"));
}
const parseWon = (text: string): bigint | null => (/^\d{1,13}$/.test(text.trim()) ? BigInt(text.trim()) : null);

// 외화 단가 글자 검사. 문제가 없으면 null, 있으면 사람이 읽을 문장. 예) ("USD","0.035") → "단가는 소수 2자리까지"
export function fxPriceProblem(currency: Currency, text: string): string | null {
  const { decimals, unitName } = CURRENCIES[currency];
  if (text.trim() === "") return "단가를 입력해 주세요";
  if (toScaled(text, decimals) === null) return decimals === 0 ? `${unitName} 단가는 소수 없이 입력해 주세요` : `단가는 소수 ${decimals}자리까지 입력해 주세요`;
  return null;
}
// 환율 글자 검사. 비어 있으면 null(작성 중에는 비워도 된다, 승인 때 필수)
export function rateProblem(text: string): string | null {
  if (text.trim() === "") return null;
  const scaled = toScaled(text, 2);
  if (scaled === null) return "환율은 소수 2자리까지 입력해 주세요";
  if (scaled === BigInt(0)) return "환율은 0보다 커야 합니다";
  return null;
}

// ── 표시 ──
const commas = (n: bigint) => n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
// 정수(센트 단위)를 통화 자릿수로 표시. 예) (123450n, 2) → "1,234.50", (90512n, 0) → "90,512"
export function formatScaled(scaled: bigint, decimals: number): string {
  if (decimals === 0) return commas(scaled);
  const base = BigInt(10) ** BigInt(decimals);
  return `${commas(scaled / base)}.${(scaled % base).toString().padStart(decimals, "0")}`;
}
// 서버가 준 외화 글자("0.50", "5000.00")를 통화 자릿수로 다시 표시. 읽을 수 없으면 원문 그대로
export function formatFxText(text: string, currency: Currency): string {
  const scaled = toScaled(text, CURRENCIES[currency].decimals);
  return scaled === null ? text : formatScaled(scaled, CURRENCIES[currency].decimals);
}
// 서버 외화 글자를 입력칸에 넣을 글자로 (쉼표 없이 통화 자릿수로). 예) ("5000.00","JPY") → "5000", ("0.5","USD") → "0.50"
export function fxInputText(text: string, currency: Currency): string {
  const d = CURRENCIES[currency].decimals;
  const scaled = toScaled(text, d);
  return scaled === null ? text : formatScaled(scaled, d).replace(/,/g, "");
}
export const formatWon = (won: number | bigint) => won.toLocaleString("ko-KR"); // 원 금액에 쉼표

// ── 계산 ──
// 수량 × 외화 단가 합계를 센트 단위 정수로. 예) 3개 × "0.50" → 150n. 비어 있거나 틀린 줄은 건너뛴다(표시는 예상이라 서버가 최종 검사)
export function fxTotalScaled(currency: Currency, lines: { quantity: string; price: string }[]): bigint {
  const d = CURRENCIES[currency].decimals;
  let sum = BigInt(0);
  for (const l of lines) {
    const price = toScaled(l.price, d);
    const count = /^\d{1,7}$/.test(l.quantity.trim()) ? BigInt(l.quantity.trim()) : null;
    if (price !== null && count !== null) sum += count * price;
  }
  return sum;
}
// 원화 환산 예상: 외화 합계(센트 단위) × 환율 ÷ 기준 단위, 총액에서 한 번만 원 미만을 버린다(BigInt 나눗셈은 0 쪽으로 버림).
// 예) 2,025.375 → (150n × 135025n) / (100 × 100 × 1) = 2025 원, 환율이 비었거나 틀리면 null
export function krwEstimate(currency: Currency, totalScaled: bigint, rateText: string): bigint | null {
  if (currency === "KRW" || rateProblem(rateText) !== null || rateText.trim() === "") return null;
  const rate = toScaled(rateText, 2)!; // 위에서 검사했다 (환율 × 100 정수)
  const { decimals, rateUnit } = CURRENCIES[currency];
  return (totalScaled * rate) / (BigInt(10) ** BigInt(decimals) * BigInt(100) * BigInt(rateUnit));
}

export type CostEstimate = { total: bigint | null; extrasTotal: bigint; missing: ("exchange_rate" | "freight")[] };
// 예상 원가 = 품목 원화 합계 + 운송비 + 부대비용 합계 (부가세 제외). 운송비 ""(미입력)과 "0"(무료)은 다르다.
// 예) 1,380,000 + 120,000 + 30,000 → 1,530,000, 운송비 "" → missing 에 "freight" (합계는 운송비 없이 계산)
export function costEstimate(goodsKrw: bigint | null, freight: string, extras: { amount: string }[]): CostEstimate {
  const extrasTotal = extras.reduce((s, e) => s + (parseWon(e.amount) ?? BigInt(0)), BigInt(0));
  const missing: CostEstimate["missing"] = [];
  if (goodsKrw === null) missing.push("exchange_rate");
  const freightWon = freight.trim() === "" ? null : parseWon(freight);
  if (freightWon === null) missing.push("freight");
  return { total: goodsKrw === null ? null : goodsKrw + (freightWon ?? BigInt(0)) + extrasTotal, extrasTotal, missing };
}

// 부대비용 줄 검사: 이름(1~50자)과 금액(0 이상 정수)이 모두 있어야 한다. 문제 없으면 null. 예) 3번째 줄 이름 없음 → "부대비용 3번 줄: 이름을 적어 주세요"
export function extraCostProblem(extras: { name: string; amount: string }[]): string | null {
  for (const [i, e] of extras.entries()) {
    if (e.name.trim() === "") return `부대비용 ${i + 1}번 줄: 이름을 적어 주세요`;
    if (e.name.trim().length > 50) return `부대비용 ${i + 1}번 줄: 이름은 50자까지입니다`;
    if (parseWon(e.amount) === null) return `부대비용 ${i + 1}번 줄: 금액(원)을 입력해 주세요`;
  }
  return null;
}

// ── 통화 바꾸기 (한 곳에서만 정한다) ──
// 통화·환율·운송비 조건·특약·품목 줄 단가는 서로 영향을 주므로 reducer 하나가 같이 바꾼다.
// 통화가 바뀌면 환율과 모든 줄의 단가 칸을 비운다(서버도 통화를 바꾸면 단가를 다시 받는다, 자동 환산 없음). 같은 통화로 "바꾸기"는 아무것도 지우지 않는다.
export type CostState<L extends { unit_price: string }> = {
  currency: Currency; // 발주서 통화
  rate: string; // 환율 글자 (기준 단위당 원)
  freightTerms: string; // 운송비 조건 코드, ""(선택 안 함) = 서버에 null
  specialTerms: string; // 특약
  lines: L[]; // 품목 줄 (unit_price 는 통화에 따라 원화 단가 또는 외화 단가)
  cleared: boolean; // 통화 변경으로 단가가 비워졌다는 안내를 보일지
};
export type CostAction<L extends { unit_price: string }> =
  | { type: "currency"; currency: Currency }
  | { type: "rate"; rate: string }
  | { type: "freightTerms"; value: string }
  | { type: "specialTerms"; value: string }
  | { type: "supplier"; currency: Currency; freightTerms: string | null; specialTerms: string | null } // 공급업체를 고르면 기본값으로 채운다
  | { type: "lines"; update: (rows: L[]) => L[] }; // 줄 추가·삭제·수정

function withCurrency<L extends { unit_price: string }>(s: CostState<L>, next: Currency): CostState<L> {
  if (next === s.currency) return s; // 같은 통화: 그대로
  return { ...s, currency: next, rate: "", lines: s.lines.map((l) => ({ ...l, unit_price: "" })), cleared: s.lines.length > 0 };
}
export function costReducer<L extends { unit_price: string }>(s: CostState<L>, a: CostAction<L>): CostState<L> {
  switch (a.type) {
    case "currency": return withCurrency(s, a.currency);
    case "rate": return { ...s, rate: a.rate };
    case "freightTerms": return { ...s, freightTerms: a.value };
    case "specialTerms": return { ...s, specialTerms: a.value };
    case "supplier": return { ...withCurrency(s, a.currency), freightTerms: a.freightTerms ?? "", specialTerms: a.specialTerms ?? "" };
    case "lines": return { ...s, lines: a.update(s.lines), cleared: false };
  }
}
