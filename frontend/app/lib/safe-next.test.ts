// safeNext 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { safeNext } from "./safe-next.ts"; // 확장자 .ts 포함 (node 가 직접 읽는다)

// 허용 경로 14개 (예시 번호 17)
const ALLOWED = [
  "/dashboard", "/inventory", "/recommendations", "/purchase-orders", "/purchase-orders/17",
  "/purchase-orders/17/document", "/receipts", "/shipments", "/products", "/suppliers",
  "/suppliers/17", "/company", "/slack", "/users",
];

test("허용 경로 14개는 그대로 통과", () => {
  assert.equal(ALLOWED.length, 14);
  for (const p of ALLOWED) assert.equal(safeNext(p), p, p);
});

test("인코딩된 허용 경로는 한 번 디코딩해 통과", () => {
  assert.equal(safeNext("%2Fpurchase-orders%2F17"), "/purchase-orders/17");
});

// 거절해야 하는 값들 (모두 /dashboard)
const REJECTED: [string, unknown][] = [
  ["null", null], ["undefined", undefined], ["숫자", 5], ["빈 문자열", ""],
  ["도메인만", "evil.com"], ["https", "https://evil.com"], ["javascript", "javascript:alert(1)"],
  ["//", "//evil.com"], ["/\\", "/\evil.com"], ["/%5C", "/%5Cevil.com"], ["/\/", "/\/evil.com"],
  ["%2F%2F", "%2F%2Fevil.com"], ["이중 인코딩", "%252F%252Fevil.com"],
  ["이중 인코딩 한 번 풀린 뒤에도 안 통과", "%2Fpurchase-orders%252F17"],
  ["..", "/purchase-orders/../users"], ["인코딩된 ..", "/purchase-orders/%2E%2E/users"],
  ["없는 경로", "/unknown-path"], ["login", "/login"], ["change-password", "/change-password"],
  ["입력 화면", "/products/new"], ["입력 화면2", "/purchase-orders/new"], ["edit", "/purchase-orders/17/edit"],
  ["가져오기", "/product-import"], ["id 가 숫자 아님", "/purchase-orders/abc"],
  ["쿼리", "/products?x=1"], ["해시", "/products#a"], ["끝 슬래시", "/dashboard/"],
  ["깨진 인코딩", "%E0%A4%A"], ["줄바꿈", "/dashboard\n"], ["인코딩된 줄바꿈", "/dashboard%0A"],
  ["공백", "/dash board"], ["널 문자", "/dashboard%00"], ["아주 긴 문자열", "/" + "a".repeat(5000)],
];

for (const [name, value] of REJECTED) {
  test(`거절 → /dashboard: ${name}`, () => assert.equal(safeNext(value), "/dashboard"));
}
