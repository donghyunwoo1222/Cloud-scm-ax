import assert from "node:assert/strict";
import test from "node:test";

import { barRatio, bucketLabel, coverNote, coverText, filterItems, isShortCover, PAGE_STEP, parseQuery, peakWord, shareText, toQuery, TOP_N, trendLabel, visibleItems } from "./sales-analytics.ts";

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

// ── #357 후속: 근거 문구, 주 단위 문구, 검색, 나눠 보기 ──

test("소진 예상일 근거: 입고 예정이 있을 때만, 리드타임 모르면 발주 정보 없음", () => {
  const base = { unit: "개", days_of_cover: 51, lead_time_days: 5, in_transit: 0 };
  assert.equal(coverNote(base), "");
  assert.equal(coverNote({ ...base, in_transit: 1500 }), "입고 예정 1,500개 포함");
  assert.equal(coverNote({ ...base, lead_time_days: null }), "발주 정보 없음");
  assert.equal(coverNote({ ...base, in_transit: 5, lead_time_days: null }), "입고 예정 5개 포함 · 발주 정보 없음");
  assert.equal(coverNote({ ...base, days_of_cover: null, in_transit: 5, lead_time_days: null }), ""); // 숫자가 없으면 근거도 없다
});

test("주 단위 문구: 단어는 고른 묶음, 7일 안 되는 주에만 (N일)", () => {
  const sunday = { start: "2026-11-22", end: "2026-11-22", days: 1, quantity: 9 }; // 기간 첫날이 일요일 → 하루짜리 주
  const week = { start: "2026-11-23", end: "2026-11-29", days: 7, quantity: 9 };
  const ongoing = { start: "2026-11-23", end: "2026-11-28", days: 6, quantity: 9 }; // 오늘 토요일, 진행 중
  assert.equal(peakWord("week"), "주");
  assert.equal(peakWord("day"), "날");
  assert.equal(trendLabel(sunday, "week"), "11/22 (1일)");
  assert.equal(trendLabel(week, "week"), "11/23~11/29");
  assert.equal(trendLabel(ongoing, "week"), "11/23~11/28 (6일)");
  assert.equal(trendLabel(sunday, "day"), "11/22"); // 일 단위는 붙이지 않는다
});

test("검색: SKU·품목명 부분 일치, 대소문자 무시, 순서 유지", () => {
  const items = [
    { product_sku: "TS-001", product_name: "티셔츠 블랙" },
    { product_sku: "cup-9", product_name: "머그컵" },
    { product_sku: "TS-002", product_name: "Tote Bag" },
  ];
  assert.deepEqual(filterItems(items, "ts-").map((i) => i.product_sku), ["TS-001", "TS-002"]);
  assert.deepEqual(filterItems(items, "  CUP ").map((i) => i.product_sku), ["cup-9"]);
  assert.deepEqual(filterItems(items, "tote").map((i) => i.product_sku), ["TS-002"]);
  assert.deepEqual(filterItems(items, "블랙").map((i) => i.product_sku), ["TS-001"]);
  assert.equal(filterItems(items, "").length, 3);
  assert.equal(filterItems(items, "없는품목").length, 0);
});

test("나눠 보기: 처음 10개, 더 보기마다 50개씩, 끝에서 멈춘다", () => {
  const items = Array.from({ length: 3000 }, (_, i) => i);
  assert.equal(visibleItems(items, TOP_N).length, 10);
  assert.equal(visibleItems(items, TOP_N + PAGE_STEP).length, 60);
  assert.equal(visibleItems(items.slice(0, 25), TOP_N + PAGE_STEP).length, 25);
});

test("검색어도 주소에 남는다 (빈 검색어는 생략)", () => {
  assert.equal(toQuery(30, "day", ""), "days=30&bucket=day");
  assert.equal(toQuery(30, "day", "  "), "days=30&bucket=day");
  const q = new URLSearchParams(toQuery(90, "week", " 티셔츠 & TS "));
  assert.deepEqual([q.get("days"), q.get("bucket"), q.get("q")], ["90", "week", "티셔츠 & TS"]);
});
