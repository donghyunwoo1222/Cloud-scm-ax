// can (발주서 버튼 표시 판단) 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { can, closedTotal, isClosedWithRemainder } from "./po.ts";

test("서버가 준 allowed_actions 에 있는 동작만 true", () => {
  const staffDraft: Parameters<typeof can>[0] = { allowed_actions: ["edit", "cancel"] };
  assert.equal(can(staffDraft, "edit"), true);
  assert.equal(can(staffDraft, "cancel"), true);
  assert.equal(can(staffDraft, "approve"), false); // 담당자 DRAFT: 승인 없음
});

test("빈 목록이면 모두 false (예: 취소된 발주서)", () => {
  assert.equal(can({ allowed_actions: [] }, "document"), false);
});

test("칸이 없는 옛 응답은 모두 false (버튼을 숨긴다)", () => {
  assert.equal(can({}, "receive"), false);
  assert.equal(can({ allowed_actions: undefined }, "cancel"), false);
});

// 잔량 마감 보조 함수 (#252): 줄은 closed_quantity 칸만 있으면 된다
const line = (closed?: number | null) => ({ closed_quantity: closed }) as { closed_quantity?: number | null };
const order = (status: "ORDERED" | "RECEIVED", ...closed: (number | null | undefined)[]) =>
  ({ status, items: closed.map(line) }) as unknown as Parameters<typeof closedTotal>[0] & Parameters<typeof isClosedWithRemainder>[0];

test("마감 5개: 합계 5, 마감된 발주", () => {
  assert.equal(closedTotal(order("RECEIVED", 5)), 5);
  assert.equal(isClosedWithRemainder(order("RECEIVED", 5)), true);
});

test("마감 0개(전부 입고돼 끝남): 마감 표시 없음", () => {
  assert.equal(isClosedWithRemainder(order("RECEIVED", 0, 0)), false);
});

test("null(RECEIVED 아님)과 값이 없는 옛 응답은 0으로 본다", () => {
  assert.equal(closedTotal(order("ORDERED", null, undefined)), 0);
  assert.equal(isClosedWithRemainder(order("ORDERED", 5)), false); // 상태가 RECEIVED 가 아니면 아님
});

test("전량 정정 뒤 마감: 마감 수량이 줄 전체", () => {
  assert.equal(closedTotal(order("RECEIVED", 100, 20)), 120);
  assert.equal(isClosedWithRemainder(order("RECEIVED", 100)), true);
});
