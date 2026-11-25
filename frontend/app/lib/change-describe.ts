// 발주서 변경 이력 한 행을 화면 글자로 바꾸는 순수 함수 (change-log.tsx 에서 옮김, 시험하려고 분리)
import { fmtTime, PO_LABELS, STATUS_LABEL } from "./po.ts"; // 시각, 기존 상태·칸 이름 표
import type { ChangeLog, PoStatus } from "./po.ts"; // 이력 모양, 상태 이름
import { FREIGHT_TERMS } from "./po-fx.ts"; // 운송비 조건 이름 (#267)

const ITEM_FIELD_LABELS: Record<string, string> = {
  quantity: "수량", closed_quantity: "마감 수량", unit_price: "단가", min_order_units: "최소 주문 수량", units_per_box: "박스 입수", box_unit_price: "박스 단가", order_unit: "발주단위", fx_unit_price: "외화 단가", fx_box_unit_price: "외화 박스 단가",
}; // 줄 안의 칸 이름 (모르는 칸은 서버 이름 그대로)

// 값 → 화면 글자. 비었으면 "없음", 상태 코드는 기존 상태 이름 표로, 공급업체 확인 시각은 서울 시각으로 (예: "ORDERED" → "발주함")
const show = (field: string, value: string | null) =>
  value === null || value === "" ? "없음" : field === "status" ? STATUS_LABEL[value as PoStatus] ?? value
    : field === "supplier_confirmed_at" ? fmtTime(value) : field === "freight_terms" ? FREIGHT_TERMS[value] ?? value : field === "freight_amount" ? `${value}원` : value; // 운송비 조건 코드는 화면 이름으로

// 이력 한 행을 한 줄 문장으로. 모르는 field 는 원래 이름을 그대로 쓴다
// 예) items[A-1].unit_price 1000→1200 → "품목 A-1 단가: 1000 → 1200", due_date 없음 → "약속 납기: 없음 → 2026-11-20"
export function describeChange(row: Pick<ChangeLog, "field" | "old_value" | "new_value">): string {
  const { field, old_value: before, new_value: after } = row;
  const match = /^items\[(.+?)\](?:\.(\w+))?$/.exec(field); // items[SKU] 또는 items[SKU].칸
  if (match && !match[2]) {
    if (before === null) return `품목 ${match[1]} 줄 추가: ${show(field, after)}`;
    if (after === null) return `품목 ${match[1]} 줄 삭제 (${show(field, before)})`;
    return `품목 ${match[1]} 줄: ${show(field, before)} → ${show(field, after)}`;
  }
  const label = match ? `품목 ${match[1]} ${ITEM_FIELD_LABELS[match[2]] ?? match[2]}` : field === "status" ? "상태" : (PO_LABELS as Record<string, string>)[field] ?? field;
  return `${label}: ${show(field, before)} → ${show(field, after)}`;
}

// 카드 배치용: 한 행을 항목 이름 / 이전 / 이후로 따로 돌려준다 (값 글자는 describeChange 와 같은 show). 예) due_date 없음→2026-11-20 → {label:"약속 납기", before:null, after:"2026-11-20"}
// before·after 가 null 이면 "(없음)" 으로 흐리게 그린다
export function describeChangeParts(row: Pick<ChangeLog, "field" | "old_value" | "new_value">): { label: string; before: string | null; after: string | null } {
  const { field, old_value: before, new_value: after } = row;
  const match = /^items\[(.+?)\](?:\.(\w+))?$/.exec(field);
  const label = match ? (match[2] ? `품목 ${match[1]} ${ITEM_FIELD_LABELS[match[2]] ?? match[2]}` : `품목 ${match[1]} 줄`) : field === "status" ? "상태" : (PO_LABELS as Record<string, string>)[field] ?? field;
  const text = (v: string | null) => (v === null || v === "" ? null : show(field, v));
  return { label, before: text(before), after: text(after) };
}

