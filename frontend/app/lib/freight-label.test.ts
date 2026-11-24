// 운송비 표시 시험: NULL=미입력, 0=무료. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { freightLabel } from "./po-fx.ts";

test("운송비 표시: 0 은 무료(0원), 미입력(null)은 미입력, 3000 은 3,000원", () => {
  assert.equal(freightLabel(0), "무료(0원)");
  assert.equal(freightLabel(null), "미입력");
  assert.equal(freightLabel(3000), "3,000원");
});
