// 운송조건·특약 구역 표시 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { RECEIVED_COST_NOTE, termsToShow } from "./po-fx.ts";

test("특약만 있으면 특약만", () => {
  assert.deepEqual(termsToShow(null, "분할 납품\n검수 후 결제"), { freight: null, special: "분할 납품\n검수 후 결제" });
});
test("운송비 조건만 있으면 조건 이름만", () => {
  const t = termsToShow("FOB", null);
  assert.equal(t?.special, null);
  assert.ok(t?.freight);
});
test("둘 다 있으면 둘 다", () => {
  const t = termsToShow("FOB", "특약");
  assert.ok(t?.freight && t.special === "특약");
});
test("둘 다 없으면(빈 문자열·공백 포함) null: 구역이 안 보인다", () => {
  assert.equal(termsToShow(null, null), null);
  assert.equal(termsToShow(null, "  "), null);
});
test("입고 기준 원가 문구", () => {
  assert.equal(RECEIVED_COST_NOTE, "품목은 입고한 수량만큼만, 운송비·부대비용은 전액 반영");
});
