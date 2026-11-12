// 발주서 화면들이 같이 쓰는 모양·이름 (서버 응답: backend/app/schemas/purchase_orders.py)

// 발주 줄 하나 (응답 items 의 한 칸)
export type PoItem = {
  id: number; // 발주 품목 번호 (입고 요청에 쓴다)
  product_id: number; // 품목 번호
  product_sku: string; // 품목 SKU
  product_name: string; // 품목명
  color?: string | null; size?: string | null; spec?: string | null; // 품목 옵션 (품목 마스터의 현재 값)
  unit: string; // 입고 현황에 붙일 품목 단위 (예: 개, 박스)
  quantity: number; // 발주 수량
  unit_price: number; // 발주 단가(원)
  box_unit_price?: number | null; // 박스 단가(원), 박스 발주 줄에서만 값이 있다
  units_per_box?: number | null; // 발주 줄에 저장한 당시 입수
  box_quantity?: number | null; // 발주 당시 박스 수
  order_unit?: string; // 발주 당시 발주단위 이름 (박스 줄이 아니면 재고 단위, 예: BOX)
  unit_factor?: number; // 발주 당시 환산계수 (박스 줄이 아니면 1)
  min_order_units?: number | null; // 발주 당시 최소 주문량(발주단위 수) 스냅샷 (#194)
  line_total?: number; // 서버가 계산한 줄 금액(원), 이전 API 응답에는 없을 수 있다
  received_quantity: number; // 누적 입고량 (입고 − 입고 정정)
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
  received_at: string | null; // 전량 입고 시각 (실제 입고일)
  cancelled_at: string | null; // 취소 시각
  emailed_at: string | null; // 마지막 메일 발송 시각 (#158)
  emailed_to: string | null; // 마지막 메일 수신 주소 (#158)
  items: PoItem[]; // 품목 줄
};

export type PoStatus = "DRAFT" | "APPROVED" | "ORDERED" | "RECEIVED" | "CANCELLED"; // 서버가 쓰는 상태 5개

export const STATUS_LABEL: Record<PoStatus, string> = {
  DRAFT: "작성 중", APPROVED: "승인됨", ORDERED: "발주함", RECEIVED: "입고 완료", CANCELLED: "취소됨",
}; // 상태 → 화면 이름

// 오류 details 의 칸 이름 → 화면 이름 (422 문장 뒤에 어느 칸인지 덧붙인다)
export const PO_LABELS = {
  supplier_id: "공급업체", due_date: "약속 납기", memo: "메모", delivery_address: "납품장소", payment_terms: "지불조건", items: "품목 줄", product_id: "품목", quantity: "수량", unit_price: "단가", movement_date: "입고일",
  box_quantity: "발주단위 수", reason: "취소 사유",
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

export function formatOrderUnitPrice(item: PoItem) {
  if (item.box_unit_price == null) return item.unit_price.toLocaleString("ko-KR");
  return `${item.box_unit_price.toLocaleString("ko-KR")} / ${item.order_unit ?? "박스"}`; // 이전 응답에는 이름이 없을 수 있다
}

export function lineAmount(item: PoItem) {
  if (item.box_unit_price != null && item.line_total !== undefined) return BigInt(item.line_total); // 박스 금액은 서버의 정확한 원 단위 값
  return BigInt(item.quantity) * BigInt(item.unit_price); // 재고 단위 줄은 곱셈부터 원 단위 정밀도를 유지한다
}
export const totalAmount = (order: PurchaseOrder) => order.items.reduce((sum, item) => sum + lineAmount(item), BigInt(0)); // 모든 품목 금액을 큰 정수로 더한다

export type PoItemSort = "registered" | "name-asc" | "name-desc"; // 등록 순서와 품목명 정렬의 두 방향

export const remainingQuantity = (item: PoItem) => item.quantity - item.received_quantity; // 발주 수량에서 누적 입고량을 빼 남은 수량을 구한다

// 표시할 행만 골라 등록 순서나 한글 품목명순으로 돌려준다.
export function visiblePoItems(items: readonly PoItem[], onlyOutstanding: boolean, sort: PoItemSort): PoItem[] {
  const rows = onlyOutstanding ? items.filter((item) => remainingQuantity(item) > 0) : [...items]; // 원본 대신 새 배열을 만든다
  if (sort === "registered") return rows; // 서버가 준 등록 순서를 그대로 쓴다
  const direction = sort === "name-asc" ? 1 : -1; // 내림차순은 이름 비교 결과의 부호를 뒤집는다
  return rows.sort((a, b) => direction * a.product_name.localeCompare(b.product_name, "ko-KR")); // 이름이 같으면 안정 정렬로 등록 순서를 유지한다
} // 표시용 배열 계산을 마친다

// 화면에서 한 번 구한 서울 날짜와 약속 납기를 비교한다.
export function overdueDays(order: Pick<PurchaseOrder, "status" | "due_date">, today: string): number {
  if (order.status !== "ORDERED" || !order.due_date || !today) return 0; // 발주함 상태이고 두 날짜를 모두 알 때만 계산한다
  const elapsed = Date.parse(today) - Date.parse(order.due_date); // 날짜 전용 문자열을 같은 UTC 자정으로 읽어 달력상의 차이를 구한다
  return Math.max(0, elapsed / 86_400_000); // 하루의 밀리초로 나누고 당일과 미래는 0으로 표시한다
}

// 시각(UTC ISO 문자열)을 서울 날짜·시각 글자로 (없으면 "-")
export const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "-");

// 시각을 서울 날짜(YYYY-MM-DD)로 (실제 입고일 표시용, 없으면 "-")
export const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }) : "-");
