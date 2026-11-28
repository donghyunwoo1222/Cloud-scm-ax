import assert from "node:assert/strict";
import test from "node:test";

import { barRatio, bucketLabel, coverText, isShortCover, parseQuery, shareText, toQuery, TOP_N, visibleItems } from "./sales-analytics.ts";

test("소진 예상일: 숫자는 '약 N일', 값이 없으면 상태 이름", () => {
  const rows: [string, "OK" | "NO_SALES_30D" | "INSUFFICIENT_DATA", number | null, string][] = [
    ["숫자", "OK", 5.4, "약 5일"],
    ["반올림", "OK", 12.9, "약 13일"],
    ["하루 미만", "OK", 0.4, "1일 미만"],
    ["재고 0", "OK", 0, "재고 없음"],
    ["판매 없음", "NO_SALES_30D", null, "판매 없음"],
    ["데이터 부족", "INSUFFICIENT_DATA", null, "데이터 부족"],
    ["OK 인데 값 없음", "OK", null, "데이터 부족"],
  ];
  for (const [name, cover_status, days_of_cover, want] of rows) assert.equal(coverText({ cover_status, days_of_cover }), want, name);
});

test("곧 소진: 7일 이하의 숫자만, 판매 없음·데이터 부족은 아니다", () => {
  assert.equal(isShortCover({ cover_status: "OK", days_of_cover: 7 }), true);
  assert.equal(isShortCover({ cover_status: "OK", days_of_cover: 0 }), true);
  assert.equal(isShortCover({ cover_status: "OK", days_of_cover: 7.1 }), false);
  assert.equal(isShortCover({ cover_status: "NO_SALES_30D", days_of_cover: null }), false);
  assert.equal(isShortCover({ cover_status: "INSUFFICIENT_DATA", days_of_cover: null }), false);
});

test("기간·묶음 쿼리: 허용 값만 따르고 나머지는 30일·일", () => {
  assert.deepEqual(parseQuery("7", "week"), { days: 7, bucket: "week" });
  assert.deepEqual(parseQuery("90", "day"), { days: 90, bucket: "day" });
  assert.deepEqual(parseQuery(null, null), { days: 30, bucket: "day" });
  assert.deepEqual(parseQuery("14", "month"), { days: 30, bucket: "day" });
});

test("비중·구간 이름·막대 비율", () => {
  assert.equal(shareText(0.4213), "42.1%");
  assert.equal(shareText(0), "0%");
  assert.equal(bucketLabel({ start: "2026-11-28", end: "2026-11-28", quantity: 1 }), "11/28");
  assert.equal(bucketLabel({ start: "2026-11-24", end: "2026-11-30", quantity: 1 }), "11/24~11/30");
  assert.equal(barRatio(5, 10), 0.5);
  assert.equal(barRatio(0, 0), 0);
});

test("TOP N 더 보기: 처음엔 앞 10개, 펼치면 전부", () => {
  const items = Array.from({ length: 25 }, (_, i) => i);
  assert.equal(visibleItems(items, false).length, TOP_N);
  assert.equal(visibleItems(items, true).length, 25);
  assert.deepEqual(visibleItems([1, 2], false), [1, 2]);
});

test("쿼리 만들기 → 되읽기가 같은 값 (새로고침해도 선택이 남는다)", () => {
  for (const days of [7, 30, 90] as const) for (const bucket of ["day", "week"] as const) {
    const q = new URLSearchParams(toQuery(days, bucket));
    assert.deepEqual(parseQuery(q.get("days"), q.get("bucket")), { days, bucket });
  }
});
