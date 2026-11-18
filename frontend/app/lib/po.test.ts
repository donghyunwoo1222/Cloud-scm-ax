// can (발주서 버튼 표시 판단) 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { can } from "./po.ts";

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
