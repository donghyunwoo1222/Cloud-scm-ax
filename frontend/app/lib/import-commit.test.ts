// isPreviewChanged 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { isPreviewChanged, PREVIEW_CHANGED_NOTICE } from "./import-commit.ts";

test("409 PREVIEW_CHANGED 만 true", () => {
  assert.equal(isPreviewChanged({ status: 409, code: "PREVIEW_CHANGED" }), true);
  assert.equal(isPreviewChanged({ status: 409, code: "IMPORT_HAS_PROBLEMS" }), false); // 다른 409
  assert.equal(isPreviewChanged({ status: 422, code: "PREVIEW_CHANGED" }), false);
  assert.equal(isPreviewChanged(new Error("x")), false);
  assert.equal(isPreviewChanged(null), false);
});

test("안내 문구", () => {
  assert.equal(PREVIEW_CHANGED_NOTICE, "미리보기 이후 데이터가 바뀌었어요. 미리보기를 다시 눌러 주세요");
});
