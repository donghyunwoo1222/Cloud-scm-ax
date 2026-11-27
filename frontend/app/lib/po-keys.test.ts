import assert from "node:assert/strict";
import test from "node:test";

import { enterAction, type EnterInput, isSaveShortcut } from "./po-keys.ts";

const base: EnterInput = { composing: false, handled: false, kind: "field", combobox: false, inLastRow: true, lastRowHasProduct: true };
const key = { key: "s", ctrlKey: true, metaKey: false, altKey: false, shiftKey: false, repeat: false };

test("마지막 줄 수량·단가 칸 Enter 는 줄을 추가한다", () => assert.equal(enterAction(base), "addLine"));
test("한글 조합 중 Enter 는 무시한다", () => assert.equal(enterAction({ ...base, composing: true }), "ignore"));
test("후보 목록이 이미 처리한 Enter 는 줄 추가보다 우선한다", () => assert.equal(enterAction({ ...base, handled: true, combobox: true }), "ignore"));
test("품목 검색 칸·앞쪽 줄·품목 미선택 줄 Enter 는 제출만 막는다", () => {
  assert.equal(enterAction({ ...base, combobox: true }), "block");
  assert.equal(enterAction({ ...base, inLastRow: false }), "block");
  assert.equal(enterAction({ ...base, lastRowHasProduct: false }), "block");
});
test("버튼·선택·여러 줄 칸 Enter 는 건드리지 않는다", () => assert.equal(enterAction({ ...base, kind: "other" }), "ignore"));

test("Ctrl+S 와 Cmd+S 는 저장 단축키다", () => {
  assert.equal(isSaveShortcut(key), true);
  assert.equal(isSaveShortcut({ ...key, ctrlKey: false, metaKey: true, key: "S" }), true);
});
test("다른 조합·키 반복은 저장 단축키가 아니다", () => {
  assert.equal(isSaveShortcut({ ...key, ctrlKey: false }), false);
  assert.equal(isSaveShortcut({ ...key, shiftKey: true }), false);
  assert.equal(isSaveShortcut({ ...key, repeat: true }), false);
  assert.equal(isSaveShortcut({ ...key, key: "a" }), false);
});
