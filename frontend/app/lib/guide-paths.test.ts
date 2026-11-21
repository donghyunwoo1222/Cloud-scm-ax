// 사용 가이드(guide.md)와 실제 화면 경로가 맞는지 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url)); // 이 파일 위치 기준이라 어디서 실행해도 같다 (frontend/app/lib)
const guide = readFileSync(join(here, "../../../backend/app/guide/guide.md"), "utf8"); // 저장소 루트의 가이드
const appDir = join(here, "..", "(app)"); // 로그인 후 화면들이 있는 폴더

// 항목 하나 = "## [ID] 제목" 머리글부터 다음 머리글 앞까지
const items = guide.split(/^## /m).slice(1).map((block) => {
  const lines = block.split("\n");
  return {
    head: lines[0],
    id: /^\[([A-Z0-9-]+)\]/.exec(lines[0])?.[1] ?? "",
    screen: /^화면: (.+)$/m.exec(block)?.[1].trim(),
    target: /^대상: (.+)$/m.exec(block)?.[1].trim(),
    status: /^상태: (.+)$/m.exec(block)?.[1].trim(),
  };
});

test("항목이 하나 이상 있고 머리글에 ID 가 있다", () => {
  assert.ok(items.length > 0);
  for (const it of items) assert.ok(it.id, `ID 형식이 틀린 머리글: ${it.head}`);
});

test("항목 ID 중복 없음", () => {
  const ids = items.map((i) => i.id);
  assert.equal(new Set(ids).size, ids.length);
});

test("모든 항목에 화면·대상·상태 줄이 있고 값이 허용 범위다", () => {
  for (const it of items) {
    assert.ok(it.screen && it.target && it.status, `${it.id}: 화면·대상·상태 줄 필요`);
    assert.ok(["사용 가능", "준비 중"].includes(it.status), `${it.id}: 상태 값 ${it.status}`);
    assert.ok(["관리자", "관리자·담당자"].includes(it.target), `${it.id}: 대상 값 ${it.target}`);
  }
});

test("사용 가능 항목의 화면 경로에 page.tsx 가 있다", () => {
  for (const it of items.filter((i) => i.status === "사용 가능")) {
    const screen = it.screen ?? "";
    assert.ok(screen.startsWith("/"), `${it.id}: 화면 경로는 / 로 시작해야 함 (${screen})`);
    const file = join(appDir, ...screen.split("/").filter(Boolean), "page.tsx");
    assert.ok(existsSync(file), `${it.id}: ${screen} 에 해당하는 page.tsx 가 없음`);
  }
});

test("준비 중 항목은 화면이 없음", () => {
  for (const it of items.filter((i) => i.status === "준비 중")) assert.equal(it.screen, "없음", it.id);
});

test("화면 경로에 숫자 ID 가 들어가지 않는다", () => {
  for (const it of items) assert.ok(!/\/\d+(\/|$)/.test(it.screen ?? ""), `${it.id}: ${it.screen}`);
});
