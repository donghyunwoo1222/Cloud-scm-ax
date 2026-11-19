// can (발주서 버튼 표시 판단) 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { can, closedTotal, isClosedWithRemainder, overdueDays, receiptText, replyGapText, replyLateDays } from "./po.ts";

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

test("지연 일수: 회신 납기가 있으면 회신 날짜가 기준", () => {
  const base = { status: "ORDERED" as const, due_date: "2026-11-20" };
  assert.equal(overdueDays({ ...base, supplier_due_date: null }, "2026-11-23"), 3); // 회신 없음: 약속 기준
  assert.equal(overdueDays({ ...base, supplier_due_date: "2026-11-25" }, "2026-11-23"), 0); // 회신이 더 늦음: 아직 지연 아님
  assert.equal(overdueDays({ ...base, supplier_due_date: "2026-11-25" }, "2026-11-27"), 2); // 회신 날짜도 지나면 지연
  assert.equal(overdueDays({ ...base, supplier_due_date: "2026-11-18" }, "2026-11-23"), 5); // 회신이 더 이름
  assert.equal(overdueDays({ ...base, supplier_due_date: "2026-11-23" }, "2026-11-23"), 0); // 오늘 경계
});

test("회신이 약속보다 늦은 일수", () => {
  assert.equal(replyLateDays({ due_date: "2026-11-20", supplier_due_date: "2026-11-22" }), 2);
  assert.equal(replyLateDays({ due_date: "2026-11-20", supplier_due_date: "2026-11-18" }), 0); // 더 이르면 0
  assert.equal(replyLateDays({ due_date: "2026-11-20", supplier_due_date: null }), 0);
});

const rLine = { quantity: 100, received_quantity: 0, unit: "개", closed_quantity: null } as Parameters<typeof receiptText>[0];

test("취소된 발주서 줄: 남음을 보이지 않고 취소됨", () => {
  assert.equal(receiptText(rLine, "CANCELLED"), "취소됨");
});

test("발주함 줄은 남음, 잔량 마감 줄은 마감을 보인다", () => {
  assert.equal(receiptText(rLine, "ORDERED"), "0 / 100개 입고 · 100개 남음");
  assert.equal(receiptText({ ...rLine, received_quantity: 95, closed_quantity: 5 }, "RECEIVED"), "95 / 100개 입고 · 마감 5개");
});

test("잔량 마감 표시는 RECEIVED 이고 마감 수량이 있을 때만 (공급업체 상세 목록도 같은 함수)", () => {
  assert.equal(isClosedWithRemainder(order("RECEIVED", 5)), true);
  assert.equal(isClosedWithRemainder({ status: "CANCELLED", items: [] }), false);
});

test("회신 기록 미리보기: 약속보다 늦음·이름·같은 날, 날짜가 하나라도 없으면 null (#265 PR4)", () => {
  assert.equal(replyGapText({ due_date: "2026-11-20", supplier_due_date: "2026-11-22" }), "약속보다 2일 늦음");
  assert.equal(replyGapText({ due_date: "2026-11-20", supplier_due_date: "2026-11-17" }), "약속보다 3일 이름");
  assert.equal(replyGapText({ due_date: "2026-11-20", supplier_due_date: "2026-11-20" }), "약속과 같은 날");
  assert.equal(replyGapText({ due_date: null, supplier_due_date: "2026-11-20" }), null);
  assert.equal(replyGapText({ due_date: "2026-11-20", supplier_due_date: null }), null);
});

test("회신 기록 버튼은 allowed_actions 의 supplier_reply 를 따른다", () => {
  assert.equal(can({ allowed_actions: ["receive", "supplier_reply"] }, "supplier_reply"), true);
  assert.equal(can({ allowed_actions: ["document"] }, "supplier_reply"), false); // 입고 완료
});
