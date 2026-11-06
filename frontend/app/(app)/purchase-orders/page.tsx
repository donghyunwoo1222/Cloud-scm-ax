"use client"; // 목록·필터를 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 상세·작성 화면 링크
import { useSearchParams } from "next/navigation"; // 주소의 ?status= 읽기 (대시보드 숫자를 누르면 걸러진 채로 열기)
import { Suspense, useEffect, useState } from "react"; // 주소 읽는 부품 감싸기, 처음 한 번 실행, 상태

import { apiList } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { seoulToday } from "../../lib/movement-form"; // 상세 화면과 같은 서울 날짜
import { overdueDays, PurchaseOrder, quantityLabel, receiptQuantitiesByUnit, STATUS_LABEL } from "../../lib/po"; // 발주서 모양과 수량 표시
import { PurchaseOrderStatusBadge, StatusBadge } from "../../lib/status-badge"; // 상세 화면과 같은 상태·납기 지연 배지
import { S } from "../../lib/styles"; // 화면 공통 스타일

type SupplierOption = { id: number; name: string }; // 거르기 선택 상자에 쓸 공급업체
const RECEIPT_DUE_LABEL = { TODAY: "오늘", OVERDUE: "지연", NEXT_7_DAYS: "향후 7일", UNSCHEDULED: "납기 미정" };

// 발주 화면 (주소 /purchase-orders): 최신순 목록 + 상태·공급업체로 거르기
// 주소의 ?status= 는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (Next.js 가 빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <PurchaseOrders />
    </Suspense>
  );
}

// 주소의 status 를 읽어 목록 부품에 넘긴다. key 를 status 로 주어, 화면이 열린 채(Next.js 가 보관한 화면) 다른 status 링크로 다시 들어와도
// 목록 부품을 새로 만들어 초기값이 다시 적용되게 한다 (useState 초기값은 처음 만들 때 한 번만 쓰인다)
function PurchaseOrders() {
  const params = useSearchParams();
  const asked = params.get("status") ?? ""; // 발주 상태는 주소에서 초기값만 읽는다
  const due = params.get("receipt_due") ?? ""; // 대시보드에서 선택한 납기 구간
  const initialDue = Object.keys(RECEIPT_DUE_LABEL).includes(due) ? due : "";
  const initial = initialDue ? "ORDERED" : Object.keys(STATUS_LABEL).includes(asked) ? asked : "";
  return <PurchaseOrdersBody key={`${initial}:${initialDue}`} initialStatus={initial} initialDue={initialDue} />;
}

function PurchaseOrdersBody({ initialStatus, initialDue }: { initialStatus: string; initialDue: string }) {
  const [status, setStatus] = useState(initialStatus); // 고른 상태 ("" 이면 전체). 처음 값은 주소에서
  const [receiptDue, setReceiptDue] = useState(initialDue); // 발주함 상태에 적용할 납기 구간
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체 ("" 이면 전체)
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]); // 공급업체 선택지
  const [today, setToday] = useState(""); // 화면이 열리면 서울 기준 오늘을 기록한다
  const [error, setError] = useState<unknown>(null); // 선택지 불러오기 오류
  const list = useList<PurchaseOrder>("/purchase-orders", { status, supplier_id: supplierId, receipt_due: receiptDue }); // 서버에서 거른 뒤 20개씩 읽는다

  useEffect(() => {
    // 비활성 업체가 낸 지난 발주서도 걸러 볼 수 있게 비활성도 포함한다
    // shortcut: 업체 100개까지만 불러온다(서버 page_size 최대). 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<SupplierOption>("/suppliers?page_size=100&include_inactive=true").then((r) => setSuppliers(r.data)).catch(setError);
  }, []);

  useEffect(() => { // 빌드 중 서버 시각을 읽지 않고 브라우저에서 날짜를 정한다
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 상세 화면과 같은 방식으로 마운트 뒤 서울 날짜를 저장한다
    setToday(seoulToday()); // 발주함 상태의 약속 납기와 비교할 날짜다
  }, []); // 목록을 처음 열 때 한 번만 계산한다

  // 조건을 바꾸면 1쪽부터 다시 본다
  function filter(set: (value: string) => void, value: string) {
    set(value); // 조건 바꾸기
    list.setPage(1); // 1쪽으로
  }

  return (
    <section>
      <h1>발주</h1>
      <p><Link href="/purchase-orders/new" style={S.linkButton}>발주서 작성</Link></p>

      <ListControls placeholder="발주번호 검색" onSearch={list.search} />
      <div style={S.toolbar}>
        <label>상태
          <select value={status} onChange={(e) => {
            const value = e.target.value;
            filter(setStatus, value);
            if (value !== "ORDERED") setReceiptDue(""); // 다른 상태에는 입고 예정 필터를 적용하지 않는다
          }} style={S.block}>
            <option value="">전체</option>
            {Object.entries(STATUS_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        <label>입고 납기
          <select value={receiptDue} onChange={(e) => {
            const value = e.target.value;
            filter(setReceiptDue, value);
            if (value) setStatus("ORDERED"); // 납기 구간을 고르면 발주함만 본다
          }} style={S.block}>
            <option value="">전체</option>
            {Object.entries(RECEIPT_DUE_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        <label>공급업체
          <select value={supplierId} onChange={(e) => filter(setSupplierId, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
      </div>
      <ErrorText error={error} />
      <ErrorText error={list.error} />

      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>발주번호</th><th>공급업체</th><th>상태</th><th style={S.num}>품목 수</th><th style={S.num}>발주 수량·입고 잔량</th><th>약속 납기</th></tr>
        </thead>
        <tbody>
          {list.rows.map((o) => { // 각 발주서의 상태와 입고 현황을 한 줄에 표시한다
            const delay = overdueDays(o, today); // 상세와 같은 규칙으로 발주함 상태의 지연 일수를 구한다
            const quantities = receiptQuantitiesByUnit(o.items); // 개와 박스처럼 다른 단위는 따로 집계한다
            const boxDetails = o.items.flatMap((i) => i.box_quantity != null && i.box_unit_price != null ? [{
              id: i.id, sku: i.product_sku, boxes: i.box_quantity, price: i.box_unit_price, quantity: i.quantity, unit: i.unit,
            }] : []); // 당시 입수·단가가 다른 줄은 따로 확인한다
            const showReceiptProgress = o.status === "ORDERED" || o.status === "RECEIVED"; // 발주함·입고 완료일 때 입고 현황을 표시한다
            return (
              <tr key={o.id} style={S.row}>
                <td style={S.nowrap}><Link href={"/purchase-orders/" + o.id}>{o.po_number}</Link></td>{/* 상세로 가는 링크는 발주번호에만 둔다 */}
                <td>{o.supplier_name}</td>{/* 서버의 공급업체 이름 */}
                <td style={S.nowrap}><PurchaseOrderStatusBadge status={o.status} /></td>{/* 발주 상태를 글자와 아이콘으로 표시한다 */}
                <td style={S.num}>{o.items.length}</td>{/* 품목 줄 수는 오른쪽 정렬한다 */}
                <td style={S.num}>
                  {Array.from(quantities, ([unit, totals]) => { // 단위 하나마다 수량을 한 줄로 표시한다
                    const partial = showReceiptProgress && totals.received > 0 && totals.remaining > 0;
                    const quantity = partial ? totals.remaining : totals.ordered;
                    const status = !showReceiptProgress ? "" : totals.remaining === 0 ? " 입고 완료" : partial ? " 남음" : " 미입고";
                    return (
                      <div key={unit}>
                        <strong>{quantityLabel(quantity, unit)}</strong>{status}
                        {partial && <span style={{ color: "var(--color-muted-foreground)", fontSize: "var(--text-xs)" }}> · 발주 {quantityLabel(totals.ordered, unit)}</span>}
                      </div>
                    );
                  })}
                  {boxDetails.length > 0 && (
                    <details>
                      <summary>박스 발주 {boxDetails.length}품목</summary>
                      {boxDetails.map((item) => (
                        <div key={item.id} style={S.sub}>
                          {item.sku} · {quantityLabel(item.boxes, "박스")} (재고 {quantityLabel(item.quantity, item.unit)}) · 박스당 {item.price.toLocaleString("ko-KR")}원
                        </div>
                      ))}
                    </details>
                  )}
                </td>
                <td style={S.nowrap}>
                  {o.due_date ?? "-"}{/* 약속 납기가 없으면 표시할 날짜가 없다 */}
                  {delay > 0 && <span style={S.sub}><StatusBadge kind="danger">납기 {delay.toLocaleString("ko-KR")}일 지연</StatusBadge></span>}{/* 납기 다음 날부터 글자와 아이콘으로 지연을 표시한다 */}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      {list.meta?.total === 0 && <p style={S.empty}>조건에 맞는 발주서가 없습니다.</p>}
      {/* 빈 목록 안내 */}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
