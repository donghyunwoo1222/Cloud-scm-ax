import assert from "node:assert/strict";
import test from "node:test";

import { confirmText, dateRange, errorMessage, screenOf } from "./supplier-reply.ts";

const base = { state: "REPLYABLE" as const, can_reply: true, replies_left: 5, supplier_confirmed_at: null };

test("screenOf: 처음 확인 / 이미 확인 / 횟수 소진 / 안내만", () => {
  assert.equal(screenOf(base), "FIRST");
  assert.equal(screenOf({ ...base, supplier_confirmed_at: "2026-11-19T01:00:00+09:00" }), "RECONFIRM");
  assert.equal(screenOf({ ...base, replies_left: 0, supplier_confirmed_at: "x" }), "EXHAUSTED");
  assert.equal(screenOf({ ...base, can_reply: false }), "EXHAUSTED");
  for (const state of ["RECEIVED", "RECEIVED_CLOSED", "CANCELLED"] as const) assert.equal(screenOf({ ...base, state, can_reply: false }), "NOTICE");
});

test("dateRange: 서울 기준 오늘과 1년 뒤, 2/29 는 2/28", () => {
  assert.deepEqual(dateRange(new Date("2026-11-19T03:00:00Z")), { min: "2026-11-19", max: "2027-11-19" });
  assert.equal(dateRange(new Date("2026-11-19T16:00:00Z")).min, "2026-11-20"); // UTC 16시 = 서울 다음 날 01시
  assert.deepEqual(dateRange(new Date("2028-02-29T03:00:00Z")), { min: "2028-02-29", max: "2029-02-28" });
});

test("errorMessage: 코드별 문구, LIMIT 은 서버 문장 포함", () => {
  assert.match(errorMessage("SUPPLIER_LINK_INVALID", ""), /만료/);
  assert.match(errorMessage("SUPPLIER_REPLY_LIMIT", "회신 5번을 모두 썼습니다."), /^회신 5번을 모두 썼습니다\. 메일로/);
  assert.match(errorMessage("SUPPLIER_REPLY_CLOSED", ""), /취소/);
  assert.match(errorMessage("VALIDATION_ERROR", ""), /1년/);
  assert.match(errorMessage("NETWORK_ERROR", ""), /연결/);
});

test("confirmText: 날짜 유무", () => {
  assert.match(confirmText("2026-12-01", 5), /2026-12-01.*4번/);
  assert.match(confirmText("", 5), /확인했다고/);
});
