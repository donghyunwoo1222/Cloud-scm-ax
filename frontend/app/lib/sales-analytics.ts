// 판매 분석 화면의 순수 함수 모음 (GET /api/v1/sales-analytics 응답을 화면 문장·값으로 바꾼다). 표 테스트로 검증한다.

export const DAY_OPTIONS = [7, 30, 90] as const; // 기간 선택지(일)
export const BUCKET_OPTIONS = [["day", "일"], ["week", "주"]] as const; // 묶음 선택지
export const TOP_N = 10; // 처음에 보이는 품목 수
export const PAGE_STEP = 50; // "더 보기" 한 번에 더 보이는 품목 수
// shortcut: 화면은 더 이상 쓰지 않는다(곧 소진은 서버 cover_alert). 기존 테스트 단언을 지키려고 남김, 사용자 확인 후 테스트와 함께 제거
export const SHORT_COVER_DAYS = 7;

export type Days = (typeof DAY_OPTIONS)[number];
export type Bucket = "day" | "week";
export type CoverStatus = "OK" | "NO_SALES_30D" | "INSUFFICIENT_DATA";
export type CoverAlert = "SHORT" | "OK" | "UNKNOWN"; // 서버가 발주 추천과 같은 규칙으로 판정한 "곧 소진" 여부

// 응답의 품목 한 줄 (backend/app/services/sales_analytics.py)
export type SalesItem = {
  product_id: number; product_sku: string; product_name: string; unit: string;
  color?: string | null; size?: string | null; spec?: string | null; is_active: boolean;
  quantity: number; share: number; abc_grade: "A" | "B" | "C" | null; // share: 0.4213 = 42.13%
  sales_30d: number; avg_daily_sales: number | null; current_stock: number;
  in_transit: number; available_stock: number; lead_time_days: number | null; // 입고 예정, 가용재고(현재고 + 입고 예정), 리드타임(발주 정보 없으면 null)
  days_of_cover: number | null; cover_status: CoverStatus; cover_alert: CoverAlert;
};
export type TrendPoint = { start: string; end: string; days: number; quantity: number }; // days: 구간에 든 날 수
export type SalesAnalytics = {
  period: { start: string; end: string; days: number; bucket: Bucket };
  source: string; total_quantity: number; trend: TrendPoint[]; items: SalesItem[];
};

// 주소의 ?days=&bucket= 읽기. 모르는 값이면 기본값(30일, 일). 예) days=90&bucket=week → {90, week}, days=14 → 30
export function parseQuery(days: string | null, bucket: string | null): { days: Days; bucket: Bucket } {
  const d = DAY_OPTIONS.find((o) => String(o) === days) ?? 30;
  return { days: d, bucket: bucket === "week" ? "week" : "day" };
}

// 소진 예상일 칸 글자. 숫자는 서버 값 그대로 반올림만 하고, 값이 없으면 상태 이름을 보여 준다(숫자를 만들지 않는다)
// 예) 5.4 → "약 5일", 0.4 → "1일 미만", 0 → "재고 없음", NO_SALES_30D → "판매 없음", INSUFFICIENT_DATA → "데이터 부족"
export function coverText(item: Pick<SalesItem, "cover_status" | "days_of_cover">): string {
  if (item.cover_status === "NO_SALES_30D") return "판매 없음";
  if (item.cover_status === "INSUFFICIENT_DATA") return "데이터 부족";
  if (item.days_of_cover === null) return "데이터 부족"; // 상태는 OK 인데 값이 없는 비정상 응답도 숫자를 지어내지 않는다
  if (item.days_of_cover <= 0) return "재고 없음";
  if (item.days_of_cover < 1) return "1일 미만";
  return `약 ${Math.round(item.days_of_cover).toLocaleString("ko-KR")}일`;
}

// (화면에서 쓰지 않음, 위 SHORT_COVER_DAYS 참고)
export function isShortCover(item: Pick<SalesItem, "cover_status" | "days_of_cover">): boolean {
  return item.cover_status === "OK" && item.days_of_cover !== null && item.days_of_cover <= SHORT_COVER_DAYS;
}

// 소진 예상일 아래 근거 한 줄. 입고 예정이 있으면 "입고 예정 500개 포함", 리드타임을 모르면 "발주 정보 없음". 둘 다 아니면 빈 값
export function coverNote(item: Pick<SalesItem, "in_transit" | "lead_time_days" | "days_of_cover" | "unit">): string {
  const notes = [];
  if (item.days_of_cover !== null && item.in_transit > 0) notes.push(`입고 예정 ${item.in_transit.toLocaleString("ko-KR")}${item.unit} 포함`);
  if (item.days_of_cover !== null && item.lead_time_days === null) notes.push("발주 정보 없음");
  return notes.join(" · ");
}

// 비중 글자. 예) 0.4213 → "42.1%", 0 → "0%"
export function shareText(share: number): string {
  return share === 0 ? "0%" : `${(share * 100).toFixed(1)}%`;
}

// 차트·숫자 표의 구간 이름. 예) 하루: "11/28", 한 주: "11/24~11/30"
export function bucketLabel(p: Omit<TrendPoint, "days">): string {
  const md = (iso: string) => iso.slice(5).replace("-", "/"); // 2026-11-28 → 11/28
  return p.start === p.end ? md(p.start) : `${md(p.start)}~${md(p.end)}`;
}

// 추이 구간 이름에 날 수를 붙인다. 주 단위에서 7일이 안 되는 주(기간 끝, 진행 중인 주)만. 예) "11/22 (1일)", "11/23~11/28 (6일)"
export function trendLabel(p: TrendPoint, bucket: Bucket): string {
  return isPartial(p, bucket) ? `${bucketLabel(p)} (${p.days}일)` : bucketLabel(p);
}

export function isPartial(p: TrendPoint, bucket: Bucket): boolean {
  return bucket === "week" && p.days < 7;
}

// "가장 많이 팔린 날/주"의 단어는 사용자가 고른 묶음으로 정한다 (첫 구간이 하루짜리 주여도 "주")
export function peakWord(bucket: Bucket): string {
  return bucket === "week" ? "주" : "날";
}

// SKU·품목명 부분 일치(대소문자 무시). 빈 검색어면 전부. 서버가 준 순서(판매량 순)는 그대로
export function filterItems<T extends Pick<SalesItem, "product_sku" | "product_name">>(items: T[], q: string): T[] {
  const needle = q.trim().toLocaleLowerCase("ko-KR");
  if (!needle) return items;
  return items.filter((i) => i.product_sku.toLocaleLowerCase("ko-KR").includes(needle) || i.product_name.toLocaleLowerCase("ko-KR").includes(needle));
}

// 앞에서 count 개만. 처음엔 TOP_N, "더 보기"마다 PAGE_STEP 씩 늘린다 (true/false 는 이전 호출 모양: 전부/TOP_N)
export function visibleItems<T>(items: T[], count: number | boolean): T[] {
  return items.slice(0, count === true ? items.length : count === false ? TOP_N : count);
}

// 차트 막대 높이(0~1). 가장 큰 값이 1. 예) (5, 10) → 0.5, 최대가 0 이면 모두 0
export function barRatio(quantity: number, max: number): number {
  return max > 0 ? quantity / max : 0;
}

// 선택을 주소 쿼리로. 예) (90, "week") → "days=90&bucket=week", 검색어가 있으면 "&q=..." (parseQuery·q 로 되읽으면 같은 값)
export function toQuery(days: Days, bucket: Bucket, q = ""): string {
  const query = q.trim();
  return `days=${days}&bucket=${bucket}` + (query ? `&q=${encodeURIComponent(query)}` : "");
}
