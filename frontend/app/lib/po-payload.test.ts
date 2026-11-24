// 발주 폼이 서버로 보내는 본문 시험: 외화 스위치 꺼짐/켜짐. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { FX_ENABLED } from "./config.ts";
import { poPayload } from "./po-fx.ts";
import type { PoFormValues } from "./po-fx.ts";

const lines = [
  { product_id: "1", quantity: "3", unit_price: "1000", box: false },
  { product_id: "2", quantity: "2", unit_price: "", box: true }, // 박스 줄: 단가는 서버가 품목 설정에서 읽는다
];
const base: PoFormValues = { currency: "KRW", rate: "", freightTerms: "FOB", freightAmount: "120000", specialTerms: " 특약 ", extras: [{ name: " 관세 ", amount: "30000" }], lines };
const FX_KEYS = ["exchange_rate", "fx_price"]; // 꺼짐일 때 본문에 없어야 하는 외화 칸

test("스위치 기본값은 꺼짐 (환경 변수가 없으면)", () => {
  assert.equal(FX_ENABLED, process.env.NEXT_PUBLIC_FX_ENABLED === "true");
  assert.equal(FX_ENABLED, false);
});

test("꺼짐: 통화는 KRW 이고 외화 칸(exchange_rate, fx_price)이 본문에 없다", () => {
  const body = poPayload(base, false);
  assert.equal(body.currency, "KRW");
  for (const key of FX_KEYS) {
    assert.equal(key in body, false, key);
    for (const item of body.items) assert.equal(key in item, false, key);
  }
  assert.deepEqual(body.items, [{ product_id: 1, quantity: 3, unit_price: 1000 }, { product_id: 2, box_quantity: 2 }]);
  assert.equal(body.freight_terms, "FOB");
  assert.equal(body.freight_amount, 120000);
  assert.deepEqual(body.extra_costs, [{ name: "관세", amount: 30000 }]);
  assert.equal(body.special_terms, "특약");
});

test("꺼짐: 화면 상태에 외화가 남아 있어도 KRW 원화 본문으로 보낸다", () => {
  const body = poPayload({ ...base, currency: "USD", rate: "1350.25" }, false);
  assert.equal(body.currency, "KRW");
  assert.equal("exchange_rate" in body, false);
  assert.equal(body.items.some((i) => "fx_price" in i), false);
});

test("꺼짐: 운송비 비움은 null, 0 은 0", () => {
  assert.equal(poPayload({ ...base, freightAmount: "" }, false).freight_amount, null);
  assert.equal(poPayload({ ...base, freightAmount: "0" }, false).freight_amount, 0);
});

test("켜짐 + 원화: 환율·외화 단가 없이 원화 본문", () => {
  const body = poPayload(base, true);
  assert.equal(body.currency, "KRW");
  assert.equal("exchange_rate" in body, false);
  assert.deepEqual(body.items[0], { product_id: 1, quantity: 3, unit_price: 1000 });
});

test("켜짐 + 외화: 통화·환율·외화 단가(글자 그대로)를 보낸다, 원화 단가는 없다", () => {
  const body = poPayload({ ...base, currency: "USD", rate: " 1350.25 ", lines: [{ product_id: "1", quantity: "3", unit_price: "0.50", box: false }, { product_id: "2", quantity: "2", unit_price: "10.00", box: true }] }, true);
  assert.equal(body.currency, "USD");
  assert.equal((body as { exchange_rate?: string | null }).exchange_rate, "1350.25");
  assert.deepEqual(body.items, [{ product_id: 1, quantity: 3, fx_price: "0.50" }, { product_id: 2, box_quantity: 2, fx_price: "10.00" }]);
  assert.equal(body.items.some((i) => "unit_price" in i), false);
});

test("켜짐 + 외화 + 환율 비움: exchange_rate 는 null (승인 전 작성 중)", () => {
  assert.equal((poPayload({ ...base, currency: "JPY", rate: "" }, true) as { exchange_rate?: string | null }).exchange_rate, null);
});
