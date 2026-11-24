// 발주서 화면들이 같이 쓰는 모양·이름 (서버 응답: backend/app/schemas/purchase_orders.py)
import { formatFxText } from "./po-fx.ts"; // 외화 줄 표시 (#267)
import type { Currency } from "./po-fx.ts"; // 통화 이름

// 발주 줄 하나 (응답 items 의 한 칸)
export type PoItem = {
  id: number; // 발주 품목 번호 (입고 요청에 쓴다)
  product_id: number; // 품목 번호
  product_sku: string; // 품목 SKU
  product_name: string; // 품목명
  color?: string | null; size?: string | null; spec?: string | null; // 품목 옵션 (품목 마스터의 현재 값)
  unit: string; // 입고 현황에 붙일 품목 단위 (예: 개, 박스)
  quantity: number; // 발주 수량
  unit_price: number | null; // 발주 단가(원). 외화 줄은 null (#267)
  fx_unit_price?: string | null; // 외화 줄의 재고 단위 단가 (서버가 글자로 준다, 예: "0.50")
  fx_box_unit_price?: string | null; // 외화 박스 줄의 발주단위 단가
  fx_line_total?: string | null; // 외화 줄 금액 (정확한 값, 줄에 원화는 두지 않는다)
  box_unit_price?: number | null; // 박스 단가(원), 박스 발주 줄에서만 값이 있다
  units_per_box?: number | null; // 발주 줄에 저장한 당시 입수
  box_quantity?: number | null; // 발주 당시 박스 수
  order_unit?: string; // 발주 당시 발주단위 이름 (박스 줄이 아니면 재고 단위, 예: BOX)
  unit_factor?: number; // 발주 당시 환산계수 (박스 줄이 아니면 1)
  min_order_units?: number | null; // 발주 당시 최소 주문량(발주단위 수) 스냅샷 (#194)
  line_total?: number; // 서버가 계산한 줄 금액(원), 이전 API 응답에는 없을 수 있다
  received_quantity: number; // 누적 입고량 (입고 − 입고 정정)
  closed_quantity?: number | null; // 잔량 마감 수량 (#252): RECEIVED 일 때만 값(발주 − 누적 입고, 0 이상), 그 밖은 null. 옛 응답에는 없을 수 있다
};

// 발주서 하나 (목록·상세·상태 변경·입고 응답이 모두 같은 모양)
export type PurchaseOrder = {
  id: number; // 발주서 번호
  po_number: string; // 발주번호 (예: PO-20261104-001)
  supplier_id: number; // 공급업체 번호
  supplier_name: string; // 공급업체명
  status: PoStatus; // 상태
  due_date: string | null; // 약속 납기 (YYYY-MM-DD)
  memo: string | null; // 메모
  delivery_address: string | null; // 납품장소 (비면 문서에 회사 주소)
  payment_terms: string | null; // 지불조건
  approved_at: string | null; // 승인 시각
  ordered_at: string | null; // 발주함 표시 시각
  has_receipts: boolean; // 발주 취소를 막는 입고 이력 여부
  allowed_actions?: PoAction[]; // 지금 누를 수 있는 동작 (#260, 서버가 상태·역할로 계산). 옛 응답에는 없을 수 있다
  received_at: string | null; // 전량 입고 시각 (실제 입고일)
  supplier_due_date: string | null; // 공급업체 회신 납기 (YYYY-MM-DD, 없으면 null, #265)
  supplier_confirmed_at: string | null; // 공급업체 확인 시각 (#265)
  supplier_reply_count: number; // 공급업체 회신 횟수 (#265)
  cancelled_at: string | null; // 취소 시각
  emailed_at: string | null; // 마지막 메일 발송 시각 (#158)
  emailed_to: string | null; // 마지막 메일 수신 주소 (#158)
  currency: Currency; // 통화 (#267)
  rate_unit: number; // 환율 기준 단위 (엔·동 100)
  exchange_rate: string | null; // 기준 단위당 원 (원화는 null)
  krw_goods_total: number | null; // 승인 때 고정한 품목 원화 합계 (승인 전 null)
  freight_terms: string | null; // 운송비 조건 코드
  freight_amount: number | null; // 운송비 (원, 내부 전용). null = 미입력, 0 = 무료
  extra_costs: { name: string; amount: number }[]; // 부대비용 줄 (원, 내부 전용)
  special_terms: string | null; // 특약
  cost: PoCost; // 원가 합산 (서버 계산, 내부 전용)
  items: PoItem[]; // 품목 줄
};

// 원가 묶음 (응답 cost, 내부 전용): 원가 = 품목 원화 합계 + 운송비 + 부대비용 (부가세 제외)
export type PoCost = {
  goods_fx_total: string | null; // 외화 발주의 품목 외화 합계 (원화 발주는 null)
  goods_krw: number | null; // 품목 원화 합계 (승인 전 예상, 승인 뒤 고정값. 외화인데 환율이 없으면 null)
  freight: number | null; // 운송비 (null = 미입력)
  extras_total: number; // 부대비용 합계
  total: number | null; // 원가 (goods_krw 가 없으면 null)
  missing: string[]; // 미입력 항목: exchange_rate, freight
  received_goods_krw: number | null; // 입고 기준 품목 원화 합계 (발주함·입고 완료만)
  received_total: number | null; // 입고 기준 원가
};

export type PoStatus = "DRAFT" | "APPROVED" | "ORDERED" | "RECEIVED" | "CANCELLED"; // 서버가 쓰는 상태 5개

// 서버 po_states.allowed_actions 가 주는 동작 이름 (backend/app/services/po_states.py)
export type PoAction = "edit" | "approve" | "order" | "cancel" | "close_remaining" | "email" | "receive" | "supplier_reply" | "document" | "remind";

// 이 발주서에서 action 을 할 수 있는지. 화면 버튼은 이것만 본다 (서버 규칙과 같은 값)
// 칸이 없는 옛 응답은 빈 목록으로 본다: 버튼이 숨는 쪽이 안전하다 (누르면 409 가 나는 버튼보다 낫다)
export const can = (order: Pick<PurchaseOrder, "allowed_actions">, action: PoAction) =>
  (order.allowed_actions ?? []).includes(action);

export const STATUS_LABEL: Record<PoStatus, string> = {
  DRAFT: "작성 중", APPROVED: "승인됨", ORDERED: "발주함", RECEIVED: "입고 완료", CANCELLED: "취소됨",
}; // 상태 → 화면 이름

// 오류 details 의 칸 이름 → 화면 이름 (422 문장 뒤에 어느 칸인지 덧붙인다)
export const PO_LABELS = {
  supplier_id: "공급업체", due_date: "약속 납기", supplier_due_date: "회신 납기", supplier_confirmed_at: "공급업체 확인", memo: "메모", delivery_address: "납품장소", payment_terms: "지불조건", items: "품목 줄", product_id: "품목", quantity: "수량", unit_price: "단가", movement_date: "입고일",
  box_quantity: "발주단위 수", reason: "사유",
  currency: "통화", exchange_rate: "환율", krw_goods_total: "품목 원화 합계", freight_terms: "운송비 조건", freight_amount: "운송비", extra_costs: "부대비용", special_terms: "특약", fx_unit_price: "외화 단가", fx_box_unit_price: "외화 박스 단가", fx_price: "외화 단가",
};

// 변경 이력 한 행 (GET /purchase-orders/{id}/change-log, #181). 서버 ChangeLogOut 과 칸 이름이 같다
export type ChangeLog = {
  id: number; // 이력 번호
  field: string; // 바뀐 항목 (status, due_date, items[SKU], items[SKU].quantity …)
  old_value: string | null; // 변경 전 값
  new_value: string | null; // 변경 후 값
  changed_by_name: string; // 바꾼 사람 이름 (이메일 없음)
  reason: string | null; // 사유 (취소 때만)
  created_at: string; // 바뀐 시각 (ISO)
};

export const MAX_ORDER_QUANTITY = 1_000_000; // 박스를 환산해도 서버의 재고 단위 상한을 지킨다
export const quantityLabel = (quantity: number, unit?: string) =>
  unit ? `${quantity.toLocaleString("ko-KR")}${unit}` : `재고 단위 ${quantity.toLocaleString("ko-KR")}`;

// 발주단위 수를 재고 단위로 환산한 글자. 화면의 환산 표시는 모두 이 함수로 만든다 (#192)
// 예) (3, "BOX", 100, "EA", "=") → "3BOX = 300EA", "()" 이면 "3BOX (300EA)". 환산할 게 없으면 (3, "EA", 1, "EA") → "3EA"
export function unitConversion(count: number, orderUnit: string, factor: number, baseUnit: string, style: "=" | "()") {
  const ordered = quantityLabel(count, orderUnit); // 발주단위 수 (예: 3BOX)
  if (factor === 1 && orderUnit === baseUnit) return ordered; // 재고 단위로 발주하는 품목은 이전 표시 그대로
  const base = quantityLabel(count * factor, baseUnit); // 재고 단위 수량 (예: 300EA)
  return style === "=" ? `${ordered} = ${base}` : `${ordered} (${base})`;
}

export function boxLimit(unitsPerBox: number, stockLimit = MAX_ORDER_QUANTITY) {
  return Math.floor(Math.min(stockLimit, MAX_ORDER_QUANTITY) / unitsPerBox); // 남은 13개가 10개입이면 최대 1박스
}

// 단가 글자. 외화 줄은 외화 단가만 ("0.50 USD", 박스는 "10.00 USD / BOX"), 원화 줄은 원 단위 숫자
export function formatOrderUnitPrice(item: PoItem, currency: Currency = "KRW") {
  const fx = item.fx_box_unit_price ?? item.fx_unit_price; // 박스 줄이면 발주단위 단가
  if (fx != null) return `${formatFxText(fx, currency)} ${currency}${item.fx_box_unit_price != null ? ` / ${item.order_unit ?? "박스"}` : ""}`;
  if (item.box_unit_price == null) return (item.unit_price ?? 0).toLocaleString("ko-KR");
  return `${item.box_unit_price.toLocaleString("ko-KR")} / ${item.order_unit ?? "박스"}`; // 이전 응답에는 이름이 없을 수 있다
}

// 줄 금액(원). 외화 줄은 원화를 만들지 않으므로 null (줄 금액 글자는 formatLineAmount 가 외화로 보여 준다)
export function lineAmount(item: PoItem): bigint | null {
  if (item.unit_price == null) return null; // 외화 줄: 원화는 총액 한 곳에만 (#282)
  if (item.box_unit_price != null && item.line_total != null) return BigInt(item.line_total); // 박스 금액은 서버의 정확한 원 단위 값
  return BigInt(item.quantity) * BigInt(item.unit_price); // 재고 단위 줄은 곱셈부터 원 단위 정밀도를 유지한다
}
// 줄 금액 글자: 원화 줄은 쉼표 숫자, 외화 줄은 "1.50 USD"
export function formatLineAmount(item: PoItem, currency: Currency): string {
  const won = lineAmount(item);
  if (won !== null) return won.toLocaleString("ko-KR");
  return item.fx_line_total != null ? `${formatFxText(item.fx_line_total, currency)} ${currency}` : "-";
}
// 원화 발주서의 합계(원). 외화 발주서는 null (총액은 외화 합계 + 원화 환산을 cost 에서 보여 준다)
export const totalAmount = (order: Pick<PurchaseOrder, "items" | "currency">): bigint | null =>
  order.currency !== "KRW" ? null : order.items.reduce((sum, item) => sum + (lineAmount(item) ?? BigInt(0)), BigInt(0)); // 모든 품목 금액을 큰 정수로 더한다
// 합계 글자: 원화 "1,234원", 외화 "1,234.50 USD" (외화 합계는 서버 cost.goods_fx_total)
export function formatTotal(order: Pick<PurchaseOrder, "items" | "currency" | "cost">): string {
  const won = totalAmount(order);
  if (won !== null) return `${won.toLocaleString("ko-KR")}원`;
  return order.cost.goods_fx_total != null ? `${formatFxText(order.cost.goods_fx_total, order.currency)} ${order.currency}` : "-";
}
export const currencyColumn = (currency: Currency) => (currency === "KRW" ? "원" : currency); // 표 머리글 "단가(원)" / "단가(USD)"

export type PoItemSort = "registered" | "name-asc" | "name-desc"; // 등록 순서와 품목명 정렬의 두 방향

export const remainingQuantity = (item: PoItem) => item.quantity - item.received_quantity; // 발주 수량에서 누적 입고량을 빼 남은 수량을 구한다

// 줄의 입고 현황 글자 (#252). 잔량 마감된 줄은 "남음" 대신 "마감", 취소된 발주서는 "남음"을 보이지 않는다
// 예) 95/100 입고 후 마감 → "95 / 100개 입고 · 마감 5개", 전량 정정 뒤 마감 → "입고 0 / 100개 · 마감 100개", 취소 → "취소됨"
export function receiptText(i: PoItem, status: PoStatus): string {
  const fmt = (n: number) => n.toLocaleString("ko-KR");
  if (status === "CANCELLED") return "취소됨"; // 취소는 입고가 없을 때만 되므로 입고·남음 수량을 적지 않는다
  const remaining = remainingQuantity(i); // 발주 − 누적 입고
  const closed = i.closed_quantity ?? 0; // 마감 수량 (RECEIVED 이고 못 받은 수량)
  if (closed > 0) return i.received_quantity === 0 ? `입고 0 / ${fmt(i.quantity)}${i.unit} · 마감 ${fmt(closed)}${i.unit}` : `${fmt(i.received_quantity)} / ${fmt(i.quantity)}${i.unit} 입고 · 마감 ${fmt(closed)}${i.unit}`;
  return remaining === 0 ? "전량 입고" : `${fmt(i.received_quantity)} / ${fmt(i.quantity)}${i.unit} 입고 · ${fmt(remaining)}${i.unit} 남음`;
}

// 발주서 전체의 마감 수량 합 (null·없는 옛 응답은 0). 예) 마감 5 + null → 5
export const closedTotal = (order: Pick<PurchaseOrder, "items">) => order.items.reduce((sum, item) => sum + (item.closed_quantity ?? 0), 0);

// 입고 완료지만 못 받은 수량을 마감한 발주서인지 (상태 이름 옆 "(잔량 마감)" 표시용)
export const isClosedWithRemainder = (order: Pick<PurchaseOrder, "status" | "items">) => order.status === "RECEIVED" && closedTotal(order) > 0;

// 표시할 행만 골라 등록 순서나 한글 품목명순으로 돌려준다.
export function visiblePoItems(items: readonly PoItem[], onlyOutstanding: boolean, sort: PoItemSort): PoItem[] {
  const rows = onlyOutstanding ? items.filter((item) => remainingQuantity(item) > 0) : [...items]; // 원본 대신 새 배열을 만든다
  if (sort === "registered") return rows; // 서버가 준 등록 순서를 그대로 쓴다
  const direction = sort === "name-asc" ? 1 : -1; // 내림차순은 이름 비교 결과의 부호를 뒤집는다
  return rows.sort((a, b) => direction * a.product_name.localeCompare(b.product_name, "ko-KR")); // 이름이 같으면 안정 정렬로 등록 순서를 유지한다
} // 표시용 배열 계산을 마친다

// 두 날짜 문자열(YYYY-MM-DD)의 달력상 차이(일). 화면의 날짜 계산은 이 함수 하나만 쓴다.
const dayGap = (later: string, earlier: string) => (Date.parse(later) - Date.parse(earlier)) / 86_400_000; // 같은 UTC 자정으로 읽어 달력 차이를 구한다

// 지연 판단에 쓰는 날짜: 회신 납기가 있으면 회신, 없으면 약속 납기 (서버 coalesce 와 같은 규칙)
export const effectiveDueDate = (order: Pick<PurchaseOrder, "due_date" | "supplier_due_date">) => order.supplier_due_date ?? order.due_date;

// 회신 납기 − 약속 납기(일). 둘 다 있어야 비교하고 없으면 null. 예) 약속 11-20, 회신 11-22 → 2, 회신 11-18 → -2
export function replyGapDays(order: Pick<PurchaseOrder, "due_date" | "supplier_due_date">): number | null {
  if (!order.due_date || !order.supplier_due_date) return null;
  return dayGap(order.supplier_due_date, order.due_date);
}

// 회신 납기가 약속 납기보다 며칠 늦은지 (없거나 같거나 빠르면 0). 예) 약속 11-20, 회신 11-22 → 2
export const replyLateDays = (order: Pick<PurchaseOrder, "due_date" | "supplier_due_date">): number => Math.max(0, replyGapDays(order) ?? 0);

// 회신 기록 입력 창의 미리보기 문장 (#265 PR4). 약속 납기나 입력 날짜가 없으면 null
export function replyGapText(order: Pick<PurchaseOrder, "due_date" | "supplier_due_date">): string | null {
  const gap = replyGapDays(order);
  if (gap === null) return null;
  return gap > 0 ? `약속보다 ${gap}일 늦음` : gap < 0 ? `약속보다 ${-gap}일 이름` : "약속과 같은 날";
}

// 화면에서 한 번 구한 서울 날짜와 기준 납기(회신 우선)를 비교한다.
export function overdueDays(order: Pick<PurchaseOrder, "status" | "due_date" | "supplier_due_date">, today: string): number {
  const due = effectiveDueDate(order); // 회신 납기가 있으면 회신 날짜가 기준
  if (order.status !== "ORDERED" || !due || !today) return 0; // 발주함 상태이고 두 날짜를 모두 알 때만 계산한다
  const elapsed = Date.parse(today) - Date.parse(due); // 날짜 전용 문자열을 같은 UTC 자정으로 읽어 달력상의 차이를 구한다
  return Math.max(0, elapsed / 86_400_000); // 하루의 밀리초로 나누고 당일과 미래는 0으로 표시한다
}

// 시각(UTC ISO 문자열)을 서울 날짜·시각 글자로 (없으면 "-")
export const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "-");

// 시각을 서울 날짜(YYYY-MM-DD)로 (실제 입고일 표시용, 없으면 "-")
export const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }) : "-");
