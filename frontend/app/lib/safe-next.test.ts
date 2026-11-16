// safeNext 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { loginUrlFor, safeNext } from "./safe-next.ts"; // 확장자 .ts 포함 (node 가 직접 읽는다)

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
  ["삼중 인코딩", "%25252F%25252Fevil.com"], ["탭 뒤 //", "/%09/evil.com"], ["유니코드 슬래시 ∕", "/∕evil.com"],
  ["전각 슬래시 ／", "／evil.com"], ["전각 점", "/．．/users"], ["대문자 경로", "/Purchase-Orders"],
  ["접두사만 같음", "/purchase-ordersEVIL"], ["끝에 점", "/dashboard."], ["앞 공백", " /dashboard"],
  ["폭 없는 공백", "/dashboard%E2%80%8B"], ["10자리 id", "/purchase-orders/1234567890"], ["10자리 id(공급업체)", "/suppliers/1234567890"],
];

for (const [name, value] of REJECTED) {
  test(`거절 → /dashboard: ${name}`, () => assert.equal(safeNext(value), "/dashboard"));
}

test("9자리 id까지는 통과", () => assert.equal(safeNext("/purchase-orders/123456789"), "/purchase-orders/123456789"));

// 로그인이 풀렸을 때 보낼 주소
test("loginUrlFor: 허용 경로는 next 로 붙인다", () => {
  assert.equal(loginUrlFor("/purchase-orders/17"), "/login?next=%2Fpurchase-orders%2F17");
  assert.equal(loginUrlFor("/recommendations"), "/login?next=%2Frecommendations");
  // 만든 주소의 next 를 다시 safeNext 에 넣으면 원래 경로로 돌아온다
  assert.equal(safeNext("%2Fpurchase-orders%2F17"), "/purchase-orders/17");
});
test("loginUrlFor: /login·/change-password·허용 밖은 그냥 /login (next 가 /login 으로 돌지 않는다)", () => {
  for (const p of ["/login", "/change-password", "/products/new", "/unknown", "/", "", "/purchase-orders/abc", "/a%2Fb", "//evil.com"]) {
    assert.equal(loginUrlFor(p), "/login", p);
  }
});
