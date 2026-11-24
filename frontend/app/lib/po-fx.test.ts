// 외화·원가 순수 함수 시험 (PR 0 규칙표 숫자 그대로). 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  costEstimate, costReducer, extraCostProblem, formatFxText, formatScaled, fxPriceInput, fxPriceProblem, fxTotalScaled,
  krwEstimate, rateInput, rateProblem, rateUnitLabel, toScaled, wonInput,
} from "./po-fx.ts";
import type { CostAction, CostState } from "./po-fx.ts";

const krw = (currency: Parameters<typeof krwEstimate>[0], lines: { quantity: string; price: string }[], rate: string) => krwEstimate(currency, fxTotalScaled(currency, lines), rate);

test("원 미만은 총액에서 한 번만 버린다 (규칙표)", () => {
  assert.equal(krw("USD", [{ quantity: "3", price: "0.50" }], "1350.25"), BigInt(2025)); // 2,025.375
  assert.equal(krw("USD", [{ quantity: "3", price: "0.50" }], "1350.45"), BigInt(2025)); // 2,025.675 → 반올림이면 2,026
  assert.equal(krw("USD", [1, 2, 3].map(() => ({ quantity: "1", price: "1.00" })), "1350.75"), BigInt(4052)); // 줄별로 버리면 4,050
});

test("엔화는 기준 단위 100: 10,000엔 × 905.12 ÷ 100", () => {
  assert.equal(krw("JPY", [{ quantity: "10000", price: "1" }], "905.12"), BigInt(90512));
  assert.equal(rateUnitLabel("JPY"), "100엔당 원");
  assert.equal(rateUnitLabel("USD"), "1달러당 원");
});

test("환율이 비었거나 틀리면 원화 예상은 null, 원화 통화도 null", () => {
  assert.equal(krw("USD", [{ quantity: "1", price: "1.00" }], ""), null);
  assert.equal(krw("USD", [{ quantity: "1", price: "1.00" }], "0"), null);
  assert.equal(krw("KRW", [{ quantity: "1", price: "1000" }], "1"), null);
});

test("원가 합산 (규칙표): 1,380,000 + 120,000 + 30,000 = 1,530,000", () => {
  const c = costEstimate(BigInt(1_380_000), "120000", [{ amount: "30000" }]);
  assert.equal(c.total, BigInt(1_530_000));
  assert.deepEqual(c.missing, []);
});

test("운송비 미입력(빈 글자)과 0 은 다르다", () => {
  assert.deepEqual(costEstimate(BigInt(1000), "", []).missing, ["freight"]);
  assert.equal(costEstimate(BigInt(1000), "", []).total, BigInt(1000)); // 합계는 운송비 없이 계산
  assert.deepEqual(costEstimate(BigInt(1000), "0", []).missing, []);
});

test("품목 원화 합계가 없으면(환율 없음) 원가 null 과 exchange_rate 미입력", () => {
  const c = costEstimate(null, "0", []);
  assert.equal(c.total, null);
  assert.deepEqual(c.missing, ["exchange_rate"]);
});

test("외화 단가 자릿수 거절: USD 0.035, JPY 0.5", () => {
  assert.notEqual(fxPriceProblem("USD", "0.035"), null);
  assert.notEqual(fxPriceProblem("JPY", "0.5"), null);
  assert.equal(fxPriceProblem("USD", "0.35"), null);
  assert.equal(fxPriceProblem("JPY", "500"), null);
  assert.notEqual(fxPriceProblem("USD", ""), null);
  assert.notEqual(fxPriceProblem("USD", "1e3"), null);
});

test("입력 칸 필터: 허용되지 않는 글자는 이전 값을 돌려준다", () => {
  assert.equal(fxPriceInput("0.5", "0.55", "USD"), "0.55");
  assert.equal(fxPriceInput("0.55", "0.555", "USD"), "0.55"); // 센트 미만 거절
  assert.equal(fxPriceInput("1", "1.", "JPY"), "1"); // 엔은 소수점 없음
  assert.equal(fxPriceInput("1", "-1", "USD"), "1");
  assert.equal(fxPriceInput("1", "1e3", "USD"), "1");
  assert.equal(fxPriceInput("", "123456789", "USD"), ""); // 9자리 정수부 거절
  assert.equal(rateInput("905.1", "905.123"), "905.1");
  assert.equal(rateInput("9999", "99999"), "9999");
  assert.equal(wonInput("12", "12a"), "12");
  assert.equal(wonInput("12", "1.5"), "12");
});

test("환율 검사: 비면 통과(작성 중), 0·셋째 자리 거절", () => {
  assert.equal(rateProblem(""), null);
  assert.equal(rateProblem("1350.25"), null);
  assert.notEqual(rateProblem("0"), null);
  assert.notEqual(rateProblem("0.00"), null);
  assert.notEqual(rateProblem("1350.255"), null);
});

test("toScaled·formatScaled: 센트 단위 정수와 표시", () => {
  assert.equal(toScaled("12.5", 2), BigInt(1250));
  assert.equal(toScaled("5000.00", 0), BigInt(5000)); // 서버가 JPY 도 "5000.00" 으로 준다
  assert.equal(toScaled("5000.50", 0), null);
  assert.equal(formatScaled(BigInt(123450), 2), "1,234.50");
  assert.equal(formatScaled(BigInt(5), 2), "0.05");
  assert.equal(formatFxText("5000.00", "JPY"), "5,000");
  assert.equal(formatFxText("0.5", "USD"), "0.50");
});

test("큰 수도 정확하다 (Number 로는 어긋나는 크기)", () => {
  // 2,000줄 × 수량 1,000,000 × 99,999,999.99 → Number 로는 정밀도가 깨지는 크기
  const total = fxTotalScaled("USD", Array.from({ length: 2000 }, () => ({ quantity: "1000000", price: "99999999.99" })));
  assert.equal(total, BigInt(2000) * BigInt(1_000_000) * BigInt(9_999_999_999));
});

test("부대비용 줄 검사", () => {
  assert.equal(extraCostProblem([{ name: "관세", amount: "0" }]), null);
  assert.match(extraCostProblem([{ name: "", amount: "1" }]) ?? "", /1번 줄: 이름/);
  assert.match(extraCostProblem([{ name: "관세", amount: "1" }, { name: "보험료", amount: "" }]) ?? "", /2번 줄: 금액/);
});

// ── 통화 변경 reducer 상태 전이 표 ──
type L = { key: number; unit_price: string };
type S = CostState<L>;
const base = (over: Partial<S> = {}): S => ({
  currency: "USD", rate: "1350.25", freightTerms: "FOB", specialTerms: "특약", lines: [{ key: 1, unit_price: "0.50" }, { key: 2, unit_price: "2.00" }], cleared: false, ...over,
});
const run = (s: S, a: CostAction<L>) => costReducer<L>(s, a);
const prices = (s: S) => s.lines.map((l) => l.unit_price);

test("통화 변경 전이 표", () => {
  // [이름, 시작 상태, 동작, 기대 통화, 기대 환율, 기대 줄 단가, 기대 안내]
  const cases: [string, S, CostAction<L>, string, string, string[], boolean][] = [
    ["USD→JPY: 환율·단가 비움", base(), { type: "currency", currency: "JPY" }, "JPY", "", ["", ""], true],
    ["USD→KRW: 환율·단가 비움", base(), { type: "currency", currency: "KRW" }, "KRW", "", ["", ""], true],
    ["KRW→USD: 단가 비움", base({ currency: "KRW", rate: "", lines: [{ key: 1, unit_price: "1000" }] }), { type: "currency", currency: "USD" }, "USD", "", [""], true],
    ["USD→USD: 아무것도 안 지움", base(), { type: "currency", currency: "USD" }, "USD", "1350.25", ["0.50", "2.00"], false],
    ["줄이 없으면 안내 없음", base({ lines: [] }), { type: "currency", currency: "EUR" }, "EUR", "", [], false],
  ];
  for (const [name, start, action, currency, rate, linePrices, cleared] of cases) {
    const next = run(start, action);
    assert.equal(next.currency, currency, name);
    assert.equal(next.rate, rate, name);
    assert.deepEqual(prices(next), linePrices, name);
    assert.equal(next.cleared, cleared, name);
  }
});

test("같은 통화 선택은 같은 상태 객체를 돌려준다", () => {
  const s = base();
  assert.equal(run(s, { type: "currency", currency: "USD" }), s);
});

test("공급업체를 고르면 기본값으로 채우고, 통화가 같으면 줄은 그대로 (한 곳이 넣은 값을 다른 곳이 지우지 않는다)", () => {
  const same = run(base(), { type: "supplier", currency: "USD", freightTerms: "CIF", specialTerms: null });
  assert.equal(same.freightTerms, "CIF");
  assert.equal(same.specialTerms, ""); // 기본값 NULL → 빈 글자(서버에는 null)
  assert.equal(same.rate, "1350.25");
  assert.deepEqual(prices(same), ["0.50", "2.00"]);
  const other = run(base(), { type: "supplier", currency: "JPY", freightTerms: null, specialTerms: "7일 이내 회신" });
  assert.equal(other.currency, "JPY");
  assert.equal(other.rate, "");
  assert.deepEqual(prices(other), ["", ""]);
  assert.equal(other.freightTerms, "");
  assert.equal(other.specialTerms, "7일 이내 회신");
});

test("환율·운송비 조건·특약·줄 편집은 통화와 서로의 값을 건드리지 않는다", () => {
  const s = base({ cleared: true });
  assert.equal(run(s, { type: "rate", rate: "1360" }).currency, "USD");
  assert.deepEqual(prices(run(s, { type: "rate", rate: "1360" })), ["0.50", "2.00"]);
  assert.equal(run(s, { type: "freightTerms", value: "" }).specialTerms, "특약");
  const edited = run(s, { type: "lines", update: (rows) => rows.map((l) => ({ ...l, unit_price: "9.99" })) });
  assert.equal(edited.currency, "USD");
  assert.equal(edited.rate, "1350.25");
  assert.equal(edited.cleared, false); // 사용자가 줄을 고치면 안내를 닫는다
});
