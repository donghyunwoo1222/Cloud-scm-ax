// describeChangeParts (변경 이력 한 행 → 항목/이전/이후) 표 시험. 실행: npm test
import assert from "node:assert/strict";
import { test } from "node:test";

import { describeChangeParts } from "./change-describe.ts";

const long = "긴 문장 ".repeat(40).trim(); // 메모처럼 긴 값
const cases: Array<[string, string, string | null, string | null, { label: string; before: string | null; after: string | null }]> = [
  ["이전 없음", "due_date", null, "2026-11-20", { label: "약속 납기", before: null, after: "2026-11-20" }],
  ["이후 없음", "due_date", "2026-11-20", null, { label: "약속 납기", before: "2026-11-20", after: null }],
  ["빈 글자는 없음 취급", "memo", "", "새 메모", { label: "메모", before: null, after: "새 메모" }],
  ["돈 값(운송비)", "freight_amount", "1500", "2000", { label: "운송비", before: "1500원", after: "2000원" }],
  ["상태 코드는 상태 이름", "status", "ORDERED", "RECEIVED", { label: "상태", before: "발주함", after: "입고 완료" }],
  ["긴 문장은 그대로", "memo", long, long, { label: "메모", before: long, after: long }],
  ["품목 칸", "items[A-1].unit_price", "1000", "1200", { label: "품목 A-1 단가", before: "1000", after: "1200" }],
  ["품목 줄 추가", "items[A-1]", null, "10", { label: "품목 A-1 줄", before: null, after: "10" }],
  ["알 수 없는 항목은 원래 이름", "mystery_field", "a", "b", { label: "mystery_field", before: "a", after: "b" }],
  ["알 수 없는 품목 칸", "items[A-1].mystery", "1", "2", { label: "품목 A-1 mystery", before: "1", after: "2" }],
];

for (const [name, field, old_value, new_value, want] of cases) {
  test(`describeChangeParts: ${name}`, () => assert.deepEqual(describeChangeParts({ field, old_value, new_value }), want));
}
