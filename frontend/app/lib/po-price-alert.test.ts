// 단가 변동 경고의 요청 본문과 "열쇠가 같을 때만 보이기" 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { test } from "node:test";

import { keepAlerts, pickAlert, priceCheckBody, visibleAlert } from "./po-price-alert.ts";
import type { PriceLine } from "./po-price-alert.ts";

const line = (product_id: string, unit_price: string, box = false): PriceLine => ({ product_id, unit_price, box });
const MSG = "지난번 1,000원보다 25% 높습니다 (PO-1, 10/02)";
const answer = (product_id: number, unit_price: number) => ({ product_id, unit_price, alert: { message: MSG } });

test("대상 줄 걸러내기: 표", () => {
  const cases: [string, PriceLine, boolean][] = [
    ["재고 단위 정수", line("5", "1250"), true],
    ["단가 0 은 대상", line("5", "0"), true],
    ["상한 1억 은 대상", line("5", "100000000"), true],
    ["박스 줄", line("5", "1250", true), false],
    ["품목 없음", line("", "1250"), false],
    ["단가 빈 값", line("5", ""), false],
    ["소수", line("5", "12.5"), false],
    ["음수", line("5", "-3"), false],
    ["너무 큰 값", line("5", "100000001"), false],
  ];
  for (const [name, l, expected] of cases) assert.equal(priceCheckBody("3", [l]) !== null, expected, name);
});

test("본문: 줄이 여러 개여도 한 번에, 대상 줄만 담는다", () => {
  assert.deepEqual(priceCheckBody("3", [line("5", "1250"), line("6", "", false), line("7", "90", true), line("8", "0")]),
    { supplier_id: 3, items: [{ product_id: 5, unit_price: 1250 }, { product_id: 8, unit_price: 0 }] });
});

test("공급업체가 없거나 대상 줄이 없으면 호출하지 않는다(null)", () => {
  assert.equal(priceCheckBody("", [line("5", "1250")]), null);
  assert.equal(priceCheckBody("3", [line("5", "", false)]), null);
  assert.equal(priceCheckBody("3", []), null);
});

test("줄 수 상한 2000", () => {
  const many = Array.from({ length: 2001 }, (_, i) => line(String(i + 1), "10"));
  assert.equal(priceCheckBody("3", many)?.items.length, 2000);
});

test("키가 같을 때만 보인다", () => {
  const alerts = keepAlerts("3", [answer(5, 1250)]);
  assert.equal(pickAlert(alerts, "3", line("5", "1250")), MSG);
  assert.equal(pickAlert(alerts, "3", line("5", "01250")), MSG); // 같은 수
});

test("단가가 바뀌면 안 보인다", () => {
  const alerts = keepAlerts("3", [answer(5, 1250)]);
  assert.equal(pickAlert(alerts, "3", line("5", "1251")), null);
  assert.equal(pickAlert(alerts, "3", line("5", "")), null);
});

test("공급업체가 바뀌면 안 보인다", () => {
  assert.equal(pickAlert(keepAlerts("3", [answer(5, 1250)]), "4", line("5", "1250")), null);
});

test("품목이 바뀌면 안 보이고, 박스 줄은 항상 안 보인다", () => {
  const alerts = keepAlerts("3", [answer(5, 1250)]);
  assert.equal(pickAlert(alerts, "3", line("6", "1250")), null);
  assert.equal(pickAlert(alerts, "3", line("5", "1250", true)), null);
});

test("응답이 늦게 와 키가 이미 달라진 경우: 지금 줄과 안 맞으니 안 보인다", () => {
  const late = keepAlerts("3", [answer(5, 1000)]); // 1000 으로 보낸 요청의 응답
  assert.equal(pickAlert(late, "3", line("5", "1250")), null); // 그사이 입력은 1250
});

test("경고 없는 응답은 보관하지 않는다", () => {
  assert.deepEqual(keepAlerts("3", [{ product_id: 5, unit_price: 1250, alert: null }]), {});
});

test("같은 품목 id 가 두 줄이어도 줄마다 따로 판단한다", () => {
  const alerts = keepAlerts("3", [answer(5, 1250), { product_id: 5, unit_price: 900, alert: null }]);
  assert.equal(pickAlert(alerts, "3", line("5", "1250")), MSG);
  assert.equal(pickAlert(alerts, "3", line("5", "900")), null);
});

test("원화로 받은 경고는 enabled=false(외화)로 바뀌면 같은 키가 입력돼도 안 보인다", () => {
  const alerts = keepAlerts("3", [answer(5, 1250)]);
  assert.equal(visibleAlert(alerts, "3", line("5", "1250"), true), MSG);
  assert.equal(visibleAlert(alerts, "3", line("5", "1250"), false), null);
});
