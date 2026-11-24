import assert from "node:assert/strict";
import test from "node:test";

import { previewStock, REASON_CHIPS, shortageText, stockTone } from "./stock-text.ts";

test("previewStock 표", () => {
  const rows: [string, "IN" | "OUT", number, number, string | null][] = [
    ["입고", "IN", 18, 1, "현재 18 → 19개"],
    ["출고", "OUT", 18, 5, "현재 18 → 13개"],
    ["출고로 정확히 0", "OUT", 18, 18, "현재 18 → 0개"],
    ["수량 0", "IN", 18, 0, null],
    ["빈 값(NaN)", "IN", 18, NaN, null],
    ["음수", "OUT", 18, -3, null],
    ["소수", "IN", 18, 1.5, null],
    ["초과 출고", "OUT", 18, 21, "재고보다 많이 출고하려고 해요 (현재 18개)"],
    ["큰 수", "IN", 1200, 3000000, "현재 1,200 → 3,001,200개"],
    ["정수 한도 초과", "IN", 10, Number.MAX_SAFE_INTEGER, null],
  ];
  for (const [name, dir, cur, qty, want] of rows) assert.equal(previewStock(dir, cur, qty), want, name);
});

test("previewStock 단위", () => assert.equal(previewStock("IN", 2, 3, "BOX"), "현재 2 → 5BOX"));

test("shortageText 표", () => {
  const rows: [string, string | null, number, number | null, string | null][] = [
    ["부족", "SHORTAGE", 8, 20, "재주문점보다 12개 모자라요"],
    ["경계(같음)", "SHORTAGE", 20, 20, null],
    ["소수 올림", "SHORTAGE", 8, 20.2, "재주문점보다 13개 모자라요"],
    ["정상", "NORMAL", 8, 20, null],
    ["판단 불가", "UNKNOWN", 8, null, null],
    ["값 없음", "SHORTAGE", 8, null, null],
    ["큰 수", "SHORTAGE", 0, 1234567, "재주문점보다 1,234,567개 모자라요"],
  ];
  for (const [name, status, avail, rp, want] of rows) assert.equal(shortageText(status, avail, rp), want, name);
});

test("stockTone 표", () => {
  assert.equal(stockTone("SHORTAGE", 0), "soldout");
  assert.equal(stockTone("NORMAL", 0), "soldout");
  assert.equal(stockTone(null, 0), "soldout");
  assert.equal(stockTone("SHORTAGE", 3), "shortage");
  assert.equal(stockTone("NORMAL", 3), "normal");
  assert.equal(stockTone("UNKNOWN", 3), "normal");
  assert.equal(stockTone(null, 3), "normal");
});

test("사유 칩 5개", () => assert.equal(new Set(REASON_CHIPS).size, 5));
