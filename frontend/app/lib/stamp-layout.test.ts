// stampRows 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { stampRows } from "./stamp-layout.ts";

test("1줄은 원 중앙 y=50, 글자 크기 = ratio×100", () => {
  const r = stampRows({ lines: ["한빛"], ratio: 0.35 })!;
  assert.equal(r.fontSize, 35);
  assert.deepEqual(r.rows, [{ text: "한빛", y: 50 }]);
});

test("2줄은 중앙 기준 위아래 대칭 (간격 = 글자×1.1)", () => {
  const r = stampRows({ lines: ["한빛", "물산"], ratio: 0.35 })!;
  assert.ok(Math.abs(r.rows[0].y - 30.75) < 1e-9);
  assert.ok(Math.abs(r.rows[1].y - 69.25) < 1e-9);
});

test("3줄은 가운데 줄이 50", () => {
  const r = stampRows({ lines: ["가나다", "라마바", "사아자"], ratio: 0.233 })!;
  assert.equal(r.rows[1].y, 50);
});

test("이상한 값은 null", () => {
  assert.equal(stampRows(null), null);
  assert.equal(stampRows({ lines: [], ratio: 0.3 }), null);
  assert.equal(stampRows({ lines: ["가"], ratio: 0 }), null);
  assert.equal(stampRows({ lines: ["가"], ratio: NaN }), null);
  assert.equal(stampRows({ lines: [""], ratio: 0.3 }), null);
});
