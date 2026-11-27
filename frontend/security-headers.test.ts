import assert from "node:assert/strict";
import test from "node:test";
import { unstable_getResponseFromNextConfig } from "next/experimental/testing/server.js";
import nextConfig from "./next.config.ts";

for (const [path, policy] of [
  ["/reset-password?token=synthetic-test-marker", "no-referrer"],
  ["/login", "strict-origin-when-cross-origin"],
  ["/supplier-reply", "no-referrer"],
]) {
  test(`${path.split("?")[0]} 응답의 보안 헤더`, async () => {
    const { headers } = await unstable_getResponseFromNextConfig({
      url: `https://scm.example.invalid${path}`,
      nextConfig,
    });
    assert.equal(headers.get("referrer-policy"), policy);
    assert.equal(headers.get("x-content-type-options"), "nosniff");
    assert.equal(headers.get("x-frame-options"), "DENY");
  });
}
