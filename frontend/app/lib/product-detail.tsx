"use client"; // 브라우저의 <dialog> 를 여닫는 부품이라 브라우저에서 실행

import { useEffect, useRef } from "react"; // 처음 그릴 때 모달 열기, dialog 요소 잡기

import { optionSummary } from "./options"; // 옵션 요약 ("검정 / M")
import { fmtTime, unitConversion } from "./po"; // 날짜·시각 표시, 발주단위 환산 ("1BOX = 100EA")
import { StatusBadge } from "./status-badge"; // 활성·비활성 배지
import { S } from "./styles"; // 화면 공통 스타일

// GET /api/v1/products 의 한 행 (재고 숫자는 없다, #31). 목록과 상세가 같은 모양이라 상세 API 를 따로 부르지 않는다(#225)
export type Product = {
  id: number; // 번호
  sku: string; // 품목 코드 (서버가 대문자로 저장)
  name: string; // 품목명
  unit: string; // 단위
  color: string | null; size: string | null; spec: string | null; // 옵션 (없으면 null)
  group_code: string | null; // 그룹 코드 (서버가 대문자로 저장)
  unit_cost: number; // 단가(원)
  units_per_box: number | null; // 박스 한 개의 재고 단위 수량
  box_unit_cost: number | null; // 박스당 구매 단가
  order_unit: string; // 발주단위 이름 (박스 설정이 없으면 재고 단위)
  min_order_units: number | null; // 최소 주문량(발주단위 수), 없으면 제한 없음 (#194)
  safety_stock: number; // 안전재고
  is_active: boolean; // 활성 여부
  default_supplier: { id: number; name: string; lead_time_days: number }; // 기본 공급업체 요약
  created_at: string; // 등록 시각 (UTC ISO 글자)
  updated_at: string; // 마지막 수정 시각
};

// 품목 상세 모달 (보기만). ESC·바깥 클릭·닫기 버튼으로 닫히고, "수정"은 모달을 닫은 뒤 화면의 수정 폼을 연다
export function ProductDetail({ product: p, onClose, onEdit }: { product: Product; onClose: () => void; onEdit: (p: Product) => void }) {
  const dialog = useRef<HTMLDialogElement>(null); // 브라우저 기본 모달
  const downOnBackdrop = useRef(false); // 누르기 시작한 곳도 바깥이어야 닫는다(안에서 글자를 끌어 선택하다 바깥에서 떼면 닫지 않게)

  useEffect(() => {
    const d = dialog.current;
    if (d && !d.open) d.showModal(); // 맨 위 층에 띄우고 뒤 화면은 누르거나 Tab 으로 갈 수 없게, 포커스는 모달 안으로(브라우저 기본 동작)
  }, []);

  const close = () => dialog.current?.close(); // 닫으면 브라우저가 연 버튼으로 포커스를 돌려주고 close 이벤트로 onClose 가 불린다
  const money = (n: number) => `${n.toLocaleString("ko-KR")}원`; // 목록 표와 같은 금액 표시 (5000 → 5,000원)
  const boxed = p.units_per_box != null; // 발주단위(박스) 설정이 있는지

  // 항목 이름과 값의 짝. 값이 없으면 "-"
  const facts: [string, string][] = [
    ["SKU", p.sku],
    ["옵션", optionSummary(p) || "-"],
    ["그룹 코드", p.group_code ?? "-"],
    ["재고 단위", p.unit],
    ["재고 단위 단가", money(p.unit_cost)],
    ["발주단위", boxed ? unitConversion(1, p.order_unit, p.units_per_box!, p.unit, "=") : "설정 없음 (재고 단위로 발주)"],
    ["발주단위 단가", p.box_unit_cost != null ? `${money(p.box_unit_cost)}/${p.order_unit}` : "-"],
    ["최소 주문량", p.min_order_units != null ? unitConversion(p.min_order_units, p.order_unit, p.units_per_box ?? 1, p.unit, "=") : "제한 없음"],
    ["안전재고", String(p.safety_stock)],
    ["기본 공급업체", `${p.default_supplier.name} (리드타임 ${p.default_supplier.lead_time_days}일)`],
    ["등록", fmtTime(p.created_at)],
    ["마지막 수정", fmtTime(p.updated_at)],
  ];

  return (
    <dialog ref={dialog} className="product-detail" aria-labelledby="product-detail-title" onClose={onClose}
      onPointerDown={(e) => { downOnBackdrop.current = e.target === e.currentTarget; }}
      onClick={(e) => { if (downOnBackdrop.current && e.target === e.currentTarget) close(); }}>
      {/* dialog 는 여백·테두리가 0 이고 안쪽 div 가 전부를 덮으므로, dialog 자신이 눌렸다면 바깥(어두운 배경)이다 */}
      <div className="product-detail-body">
        <div style={S.detailHeader}>
          <h2 id="product-detail-title" style={{ ...S.detailTitle, margin: 0, overflowWrap: "anywhere" }}>
            {p.name}
            {p.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}
          </h2>
          <button type="button" onClick={close} autoFocus>닫기</button>{/* 열리면 이 버튼에 포커스 */}
        </div>
        <div className="photo-slot" role="img" aria-label="사진 없음">사진 없음</div>
        {/* 사진 자리만 둔다. 업로드는 아직 없다(#225) */}
        <dl style={{ ...S.detailHistory, marginTop: "var(--space-md)" }}>
          {facts.map(([label, value]) => (
            <div key={label} style={S.detailHistoryCell}>
              <dt style={S.detailLabel}>{label}</dt>
              <dd style={{ ...S.detailHistoryValue, overflowWrap: "anywhere" }}>{value}</dd>
            </div>
          ))}
        </dl>
        <div style={{ ...S.buttons, marginTop: "var(--space-md)", justifyContent: "flex-end" }}>
          <button type="button" onClick={() => { close(); onEdit(p); }}>수정</button>
          {/* 모달은 보기만. 수정·비활성은 지금처럼 위쪽 수정 폼에서 한다 */}
        </div>
      </div>
    </dialog>
  );
}
