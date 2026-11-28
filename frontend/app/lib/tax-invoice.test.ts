// 세금계산서 수취 카드의 순수 함수 시험 (#268). 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { chipFilter, poListQuery } from "./po.ts";
import {
  differenceText, formProblem, parseWon, shouldFetchTaxInvoices, shouldShowCard, showRoundingNote, splitInvoices,
  statusBadge, taxInvoiceErrorText, taxMismatchNote, vatHint,
} from "./tax-invoice.ts";

test("결과 문구: PENDING 은 차이 숫자 없이 '입고 후 대조됩니다'", () => {
  assert.equal(statusBadge("PENDING").text, "입고 후 대조됩니다");
  assert.equal(differenceText({ status: "PENDING", difference: 0 }), null);
  assert.equal(statusBadge("MISSING").text, "미수취");
  assert.equal(statusBadge("MATCHED").text, "일치");
  assert.equal(statusBadge("DIFFERENT").kind, "danger"); // 배지에는 항상 글자가 들어 있다
});

test("차이 문구: 계산서 − 입고 부호로 많음/적음, 쉼표 원 단위", () => {
  assert.equal(differenceText({ status: "DIFFERENT", difference: 50_000 }), "계산서가 입고 금액보다 50,000원 많음");
  assert.equal(differenceText({ status: "DIFFERENT", difference: -18_000 }), "계산서가 입고 금액보다 18,000원 적음");
  assert.equal(differenceText({ status: "MATCHED", difference: 0 }), null);
  assert.equal(differenceText({ status: "MISSING", difference: -48_000 }), null); // 미수취는 차이 문장 대신 '미수취'
});

test("원 미만 안내: 차이가 있고 |차이| < 입고된 줄 수일 때만", () => {
  assert.equal(showRoundingNote({ status: "DIFFERENT", difference: 2, line_count: 3 }), true);
  assert.equal(showRoundingNote({ status: "DIFFERENT", difference: -2, line_count: 3 }), true); // 부호와 무관
  assert.equal(showRoundingNote({ status: "DIFFERENT", difference: 3, line_count: 3 }), false); // 줄 수와 같으면 아님
  assert.equal(showRoundingNote({ status: "DIFFERENT", difference: 1, line_count: 0 }), false); // 입고 줄이 없으면 아님
  assert.equal(showRoundingNote({ status: "MATCHED", difference: 0, line_count: 5 }), false);
});

test("세액 안내: 예상 세액과 다르면 문구, 같으면 없음", () => {
  assert.equal(taxMismatchNote({ tax_amount: 1_000, tax_expected: 1_000 }), null);
  assert.equal(taxMismatchNote({ tax_amount: 1_100, tax_expected: 1_000 }), "세액이 공급가액의 10%와 다릅니다(예상 1,000원)");
  assert.equal(taxMismatchNote({ tax_amount: 0, tax_expected: 0 }), null);
});

test("카드 표시: 발주함·입고 완료는 항상, 취소됨은 계산서가 있을 때만, 작성 중·승인됨은 조회도 안 한다", () => {
  assert.equal(shouldShowCard("ORDERED", 0), true);
  assert.equal(shouldShowCard("RECEIVED", 0), true);
  assert.equal(shouldShowCard("CANCELLED", 0), false);
  assert.equal(shouldShowCard("CANCELLED", 2), true);
  assert.equal(shouldShowCard("DRAFT", 3), false);
  assert.equal(shouldFetchTaxInvoices("DRAFT"), false);
  assert.equal(shouldFetchTaxInvoices("APPROVED"), false);
  assert.equal(shouldFetchTaxInvoices("ORDERED"), true);
  assert.equal(shouldFetchTaxInvoices("CANCELLED"), true); // 계산서가 남았는지 알려면 한 번 읽어야 한다
});

test("금액 입력: 쉼표 허용, 소수·음수·글자·상한 초과는 null, 세액 힌트는 10% 버림", () => {
  assert.equal(parseWon("1,000"), 1000);
  assert.equal(parseWon("0"), 0);
  assert.equal(parseWon("1.5"), null);
  assert.equal(parseWon("-1"), null);
  assert.equal(parseWon("abc"), null);
  assert.equal(parseWon(""), null);
  assert.equal(parseWon("1000000000001"), null); // 1조 초과
  assert.equal(vatHint("10005"), 1000);
  assert.equal(vatHint("x"), null);
});

test("기록 폼 검사: 번호·날짜·금액 문제를 첫 문제 하나로", () => {
  const ok = { number: "INV-1", date: "2026-11-28", supply: "10000", tax: "1000" };
  assert.equal(formProblem(ok, "2026-11-28"), null); // 오늘은 가능
  assert.equal(formProblem({ ...ok, number: "  " }, "2026-11-28"), "계산서 번호를 입력해 주세요.");
  assert.equal(formProblem({ ...ok, date: "2026-11-29" }, "2026-11-28"), "발행일은 오늘 이후로 할 수 없어요.");
  assert.ok(formProblem({ ...ok, supply: "-5" }, "2026-11-28")?.startsWith("공급가액"));
  assert.ok(formProblem({ ...ok, tax: "1.5" }, "2026-11-28")?.startsWith("세액"));
});

test("오류 문구: 코드별 사유 문장, 모르는 코드는 일반 문장", () => {
  assert.equal(taxInvoiceErrorText({ code: "DUPLICATE_TAX_INVOICE" }), "같은 공급업체에 같은 번호가 이미 있어요. 번호를 확인해 주세요.");
  assert.equal(taxInvoiceErrorText({ code: "ALREADY_CANCELLED" }), "이미 취소된 세금계산서예요.");
  assert.ok(taxInvoiceErrorText({ code: "INVALID_STATUS" }).includes("기록할 수 없어요"));
  assert.ok(taxInvoiceErrorText(new Error("x")).includes("처리하지 못했어요"));
});

test("취소한 계산서는 따로 모은다", () => {
  const base = { id: 1, invoice_number: "A", issue_date: "2026-11-01", supply_amount: 1, tax_amount: 0, total: 1, tax_expected: 0, memo: null, created_by_name: null, created_at: "", cancelled_by_name: null, cancel_reason: null };
  const out = splitInvoices([{ ...base, cancelled_at: null }, { ...base, id: 2, cancelled_at: "2026-11-02T00:00:00Z" }]);
  assert.deepEqual([out.active.length, out.cancelled.length], [1, 1]);
});

test("목록 주소: 미수취 토글은 상태·납기와 독립이고 꺼져 있으면 주소에 없다", () => {
  assert.equal(poListQuery("", "", true), "?tax_invoice=missing");
  assert.equal(poListQuery("ORDERED", "TODAY", true), "?status=ORDERED&receipt_due=TODAY&tax_invoice=missing");
  assert.equal(poListQuery("RECEIVED", "", false), "?status=RECEIVED");
  assert.equal(poListQuery("", ""), ""); // 기존 호출은 그대로
  const next = chipFilter("RECEIVED", "TODAY"); // 칩을 바꿔도 토글은 호출한 쪽이 그대로 넘긴다
  assert.equal(poListQuery(next.status, next.receiptDue, true), "?status=RECEIVED&tax_invoice=missing");
});
