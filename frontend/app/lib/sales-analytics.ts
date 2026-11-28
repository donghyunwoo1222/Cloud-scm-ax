// 판매 분석 화면의 순수 함수 모음 (GET /api/v1/sales-analytics 응답을 화면 문장·값으로 바꾼다). 표 테스트로 검증한다.

export const DAY_OPTIONS = [7, 30, 90] as const; // 기간 선택지(일)
export const BUCKET_OPTIONS = [["day", "일"], ["week", "주"]] as const; // 묶음 선택지
export const TOP_N = 10; // 처음에 보이는 품목 수 (나머지는 "더 보기")
export const SHORT_COVER_DAYS = 7; // 소진 예상일이 이 값 이하면 "곧 소진" (임시값: 공급업체별 리드타임이 이 응답에 없어 일주일로 둔다)

export type Days = (typeof DAY_OPTIONS)[number];
export type Bucket = "day" | "week";
export type CoverStatus = "OK" | "NO_SALES_30D" | "INSUFFICIENT_DATA";

// 응답의 품목 한 줄 (backend/app/services/sales_analytics.py)
export type SalesItem = {
  product_id: number; product_sku: string; product_name: string; unit: string;
  color?: string | null; size?: string | null; spec?: string | null; is_active: boolean;
  quantity: number; share: number; abc_grade: "A" | "B" | "C" | null; // share: 0.4213 = 42.13%
  sales_30d: number; avg_daily_sales: number | null; current_stock: number;
  days_of_cover: number | null; cover_status: CoverStatus;
};
export type TrendPoint = { start: string; end: string; quantity: number };
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

// 곧 소진되는 품목인가 (숫자가 있을 때만). 예) 6.9일 → true, 7.0일 → true, 7.1일 → false, 판매 없음 → false
export function isShortCover(item: Pick<SalesItem, "cover_status" | "days_of_cover">): boolean {
  return item.cover_status === "OK" && item.days_of_cover !== null && item.days_of_cover <= SHORT_COVER_DAYS;
}

// 비중 글자. 예) 0.4213 → "42.1%", 0 → "0%"
export function shareText(share: number): string {
  return share === 0 ? "0%" : `${(share * 100).toFixed(1)}%`;
}

// 차트·숫자 표의 구간 이름. 예) 하루: "11/28", 한 주: "11/24~11/30"
export function bucketLabel(p: TrendPoint): string {
  const md = (iso: string) => iso.slice(5).replace("-", "/"); // 2026-11-28 → 11/28
  return p.start === p.end ? md(p.start) : `${md(p.start)}~${md(p.end)}`;
}

// 앞에서 TOP N 만 (펼치면 전부). 서버가 판매량 순으로 주므로 순서는 그대로 둔다
export function visibleItems<T>(items: T[], expanded: boolean): T[] {
  return expanded ? items : items.slice(0, TOP_N);
}

// 차트 막대 높이(0~1). 가장 큰 값이 1. 예) (5, 10) → 0.5, 최대가 0 이면 모두 0
export function barRatio(quantity: number, max: number): number {
  return max > 0 ? quantity / max : 0;
}

// 선택을 주소 쿼리로. 예) (90, "week") → "days=90&bucket=week" (parseQuery 로 되읽으면 같은 값)
export function toQuery(days: Days, bucket: Bucket): string {
  return `days=${days}&bucket=${bucket}`;
}
