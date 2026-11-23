import assert from "node:assert/strict";
import test from "node:test";

import { blockedText, reminderErrorText, reminderPanelOpen } from "./reminder.ts";

const err = (status: number, code: string, details: unknown = null, message = "서버 원문 SMTP 535 secret") => ({ status, code, message, details });

test("정해 둔 코드는 모두 서버 원문 없이 한국어 문장", () => {
  for (const [status, code] of [[503, "REMINDER_DISABLED"], [503, "MAIL_NOT_CONFIGURED"], [409, "INVALID_STATUS"], [409, "NOT_OVERDUE"],
    [409, "NO_SUPPLIER_EMAIL"], [409, "REMINDER_LIMIT"], [409, "REMINDER_TOO_SOON"], [409, "REMINDER_DAILY_LIMIT"], [500, "MAIL_SENT_NOT_SAVED"]] as const) {
    const text = reminderErrorText(err(status, code));
    assert.ok(/[가-힣]/.test(text), code);
    assert.ok(!text.includes("SMTP"), `${code}: 서버 원문이 화면에 나온다`);
  }
});

test("REMINDER_TOO_SOON: next_allowed_at 을 서울 시각으로 보여 준다", () => {
  const text = reminderErrorText(err(409, "REMINDER_TOO_SOON", { next_allowed_at: "2026-11-25T00:30:00+00:00" }));
  assert.ok(text.includes("2026. 11. 25. 오전 9:30:00"), text); // UTC 00:30 = 서울 09:30
  assert.ok(reminderErrorText(err(409, "REMINDER_TOO_SOON")).includes("잠시 뒤"));
});

test("REMINDER_LIMIT: 상한 횟수를 넣고, 없으면 일반 문장", () => {
  assert.ok(reminderErrorText(err(409, "REMINDER_LIMIT", { count: 3, limit: 3 })).includes("3번"));
  assert.ok(reminderErrorText(err(409, "REMINDER_LIMIT")).includes("최대 횟수"));
});

test("MAIL_FAILED: 서버가 준 독촉용 문장을 쓰고, 비면 다시 시도 가능 문장", () => {
  assert.equal(reminderErrorText(err(502, "MAIL_FAILED", null, "메일 서버 로그인에 실패했습니다. 다시 시도할 수 있습니다.")), "메일 서버 로그인에 실패했습니다. 다시 시도할 수 있습니다.");
  assert.ok(reminderErrorText(err(502, "MAIL_FAILED", null, "")).includes("다시 시도해도 됩니다"));
});

test("모르는 500·4xx 는 원문 없는 일반 문장", () => {
  const server = reminderErrorText(err(500, "INTERNAL"));
  assert.ok(server.includes("서버에 문제") && !server.includes("SMTP"));
  assert.ok(!reminderErrorText(err(422, "VALIDATION")).includes("SMTP"));
});

test("blockedText: 한도 없으면 빈 글자, 있으면 코드별 문장", () => {
  const base = { max_per_order: 3, next_allowed_at: "2026-11-25T00:30:00+00:00" };
  assert.equal(blockedText({ ...base, blocked: null }), "");
  assert.ok(blockedText({ ...base, blocked: "REMINDER_TOO_SOON" }).includes("오전 9:30"));
  assert.ok(blockedText({ ...base, blocked: "REMINDER_LIMIT" }).includes("3번"));
  assert.ok(blockedText({ ...base, blocked: "REMINDER_DAILY_LIMIT" }).includes("내일"));
});

test("reminderPanelOpen: 버튼을 눌러 연 발주서에서 remind 가 가능할 때만 열린다", () => {
  assert.equal(reminderPanelOpen(null, "5", true), false); // 누르지 않았으면 닫힘
  assert.equal(reminderPanelOpen("5", "5", true), true);
  assert.equal(reminderPanelOpen("5", "5", false), false); // remind 가 사라지면 닫힘
  assert.equal(reminderPanelOpen("5", "6", true), false); // 다른 발주서로 바뀌면 닫힘
});

test("MAIL_SENT_NOT_SAVED: 메일은 나갔다는 뜻과 다시 보내지 말라는 뜻이 모두 들어 있다", () => {
  const text = reminderErrorText(err(500, "MAIL_SENT_NOT_SAVED"));
  assert.ok(text.includes("보냈지만"), text); // 메일은 나갔다
  assert.ok(text.includes("다시 보내지 말"), text); // 재전송 금지
});

test("모르는 코드는 상태 코드별 일반 문장 (원문 없음)", () => {
  assert.ok(reminderErrorText(err(404, "X")).includes("찾을 수 없"));
  assert.ok(reminderErrorText(err(403, "X")).includes("권한"));
});
