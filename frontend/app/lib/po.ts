// 발주서 화면들이 같이 쓰는 모양·이름 (서버 응답: backend/app/schemas/purchase_orders.py)

// 발주 줄 하나 (응답 items 의 한 칸)
export type PoItem = {
  id: number; // 발주 품목 번호 (입고 요청에 쓴다)
  product_id: number; // 품목 번호
  product_sku: string; // 품목 SKU
  product_name: string; // 품목명
  quantity: number; // 발주 수량
  unit_price: number; // 발주 단가(원)
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
  approved_at: string | null; // 승인 시각
  ordered_at: string | null; // 발주함 표시 시각
  received_at: string | null; // 전량 입고 시각 (실제 입고일)
  cancelled_at: string | null; // 취소 시각
  items: PoItem[]; // 품목 줄
};

export type PoStatus = "DRAFT" | "APPROVED" | "ORDERED" | "RECEIVED" | "CANCELLED"; // 서버가 쓰는 상태 5개

export const STATUS_LABEL: Record<PoStatus, string> = {
  DRAFT: "작성 중", APPROVED: "승인됨", ORDERED: "발주함", RECEIVED: "입고 완료", CANCELLED: "취소됨",
}; // 상태 → 화면 이름

// 오류 details 의 칸 이름 → 화면 이름 (422 문장 뒤에 어느 칸인지 덧붙인다)
export const PO_LABELS = {
  supplier_id: "공급업체", due_date: "약속 납기", memo: "메모", items: "품목 줄", product_id: "품목", quantity: "수량", unit_price: "단가", movement_date: "입고일",
};

export const totalQuantity = (order: PurchaseOrder) => order.items.reduce((sum, i) => sum + i.quantity, 0); // 줄 수량 합계 (예: 100 + 50 → 150)

// 시각(UTC ISO 문자열)을 서울 날짜·시각 글자로 (없으면 "-")
export const fmtTime = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) : "-");

// 시각을 서울 날짜(YYYY-MM-DD)로 (실제 입고일 표시용, 없으면 "-")
export const fmtDate = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }) : "-");
