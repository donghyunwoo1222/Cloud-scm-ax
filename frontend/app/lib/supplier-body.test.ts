// 공급업체 폼 본문 시험: 외화 스위치 꺼짐/켜짐. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { supplierBody } from "./supplier-body.ts";
import type { SupplierForm } from "./supplier-body.ts";

const form: SupplierForm = {
  name: "A상사", lead_time_days: "5", contact_name: "", phone: "", email: "", payment_terms: "", memo: "",
  default_currency: "USD", default_freight_terms: "", default_special_terms: " 특약 ",
};

test("꺼짐: default_currency 키가 본문에 없다 (수정해도 기존 기본 통화를 덮어쓰지 않는다)", () => {
  const body = supplierBody(form, false);
  assert.equal("default_currency" in body, false);
  assert.equal(body.default_freight_terms, null); // 선택 안 함 → null
  assert.equal(body.default_special_terms, "특약");
  assert.equal(body.lead_time_days, 5);
});

test("켜짐: 고른 기본 통화가 본문에 들어간다", () => {
  assert.equal(supplierBody(form, true).default_currency, "USD");
});
