import assert from "node:assert/strict";
import test from "node:test";

import { kindLabel, resultText } from "./email-log.ts";

test("kindLabel: 종류 이름, 모르는 값은 그대로", () => {
  assert.equal(kindLabel("ORDER"), "발주서");
  assert.equal(kindLabel("REMINDER"), "독촉");
  assert.equal(kindLabel("X"), "X");
});

test("resultText: 성공 / 저장 실패 / 실패 코드별 문장", () => {
  assert.equal(resultText({ result: "SENT", failure_code: null }), "성공");
  assert.equal(resultText({ result: "UNSAVED", failure_code: null }), "메일은 나갔으나 기록 저장에 실패했습니다");
  assert.equal(resultText({ result: "FAILED", failure_code: "AUTH" }), "실패: 메일 서버 로그인에 실패했습니다.");
  assert.equal(resultText({ result: "FAILED", failure_code: "RECIPIENT_REFUSED" }), "실패: 메일 서버가 받는 주소를 거부했습니다.");
  assert.equal(resultText({ result: "FAILED", failure_code: "TIMEOUT" }), "실패: 메일 서버가 시간 안에 응답하지 않았습니다.");
  assert.equal(resultText({ result: "FAILED", failure_code: "CONNECTION" }), "실패: 메일 서버에 연결하지 못했습니다.");
  assert.equal(resultText({ result: "FAILED", failure_code: "OTHER" }), "실패: 발송 중 오류가 났습니다.");
});

test("resultText: 모르는 코드·빈 코드는 OTHER 문장", () => {
  assert.equal(resultText({ result: "FAILED", failure_code: "NEW_CODE" }), "실패: 발송 중 오류가 났습니다.");
  assert.equal(resultText({ result: "FAILED", failure_code: null }), "실패: 발송 중 오류가 났습니다.");
});
