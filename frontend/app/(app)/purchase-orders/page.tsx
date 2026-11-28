"use client"; // 목록·필터를 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 상세·작성 화면 링크
import { usePathname, useRouter, useSearchParams } from "next/navigation"; // 주소의 ?status= 읽고 쓰기 (칩·대시보드 링크 모두 주소가 기준)
import { Suspense, useEffect, useState } from "react"; // 주소 읽는 부품 감싸기, 처음 한 번 실행, 상태

import { api, apiListAll } from "../../lib/api"; // 공통 API 호출 함수
import { Field } from "../../lib/field"; // 모바일에서 라벨이 테두리에 걸리는 입력 항목
import { ExportButton } from "../../lib/export-button"; // 내보내기 (#191)
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { seoulToday } from "../../lib/movement-form"; // 상세 화면과 같은 서울 날짜
import { chipFilter, closedTotal, isClosedWithRemainder, overdueDays, poListQuery, PurchaseOrder, remainingQuantity, STATUS_LABEL } from "../../lib/po"; // 상세와 같은 입고 잔량 기준
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

// 상태·납기 구간은 주소(?status=, ?receipt_due=)가 기준이다. 칩을 누르면 주소를 바꾸고(새로고침해도 유지), 검색·공급업체는 그대로 둔다
function PurchaseOrders() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const asked = params.get("status") ?? "";
  const due = params.get("receipt_due") ?? "";
  const receiptDue = Object.keys(RECEIPT_DUE_LABEL).includes(due) ? due : ""; // 대시보드에서 선택한 납기 구간
  const status = receiptDue ? (asked && Object.keys(STATUS_LABEL).includes(asked) ? asked : "ORDERED") : Object.keys(STATUS_LABEL).includes(asked) ? asked : ""; // 납기 구간은 발주함만 보므로 상태가 없으면 발주함
  const taxMissing = params.get("tax_invoice") === "missing"; // 세금계산서 미수취 토글 (#268). 상태·납기와 독립이라 칩을 바꿔도 유지된다
  function setUrl(nextStatus: string, nextDue: string, nextTax: boolean = taxMissing) {
    router.replace(pathname + poListQuery(nextStatus, nextDue, nextTax), { scroll: false }); // 맨 위로 튀지 않게
  }
  return <PurchaseOrdersBody status={status} receiptDue={receiptDue} taxMissing={taxMissing} setUrl={setUrl} />;
}

function PurchaseOrdersBody({ status, receiptDue, taxMissing, setUrl }: { status: string; receiptDue: string; taxMissing: boolean; setUrl: (status: string, due: string, tax?: boolean) => void }) {
  const [counts, setCounts] = useState<Record<string, number> | null>(null); // 상태별 건수 (상태 조건만 뺀 같은 필터)
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체 ("" 이면 전체)
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]); // 공급업체 선택지
  const [today, setToday] = useState(""); // 화면이 열리면 서울 기준 오늘을 기록한다
  const [error, setError] = useState<unknown>(null); // 선택지 불러오기 오류
  const list = useList<PurchaseOrder>("/purchase-orders", { status, supplier_id: supplierId, receipt_due: receiptDue, tax_invoice: taxMissing ? "missing" : "" }); // 서버에서 거른 뒤 20개씩 읽는다

  const countQuery = new URLSearchParams(); // 목록과 같은 검색·공급업체·납기 구간, 상태만 뺀다
  if (list.q) countQuery.set("q", list.q);
  if (supplierId) countQuery.set("supplier_id", supplierId);
  if (receiptDue) countQuery.set("receipt_due", receiptDue);
  if (taxMissing) countQuery.set("tax_invoice", "missing"); // 칩 건수도 목록과 같은 미수취 필터로 센다
  const countPath = `/purchase-orders/status-counts?${countQuery}`;
  useEffect(() => {
    let cancelled = false; // 조건을 빨리 바꿨을 때 늦게 온 이전 건수는 버린다
    api<Record<string, number>>(countPath).then((c) => { if (!cancelled) setCounts(c); }).catch((e) => { if (!cancelled) setError(e); });
    return () => { cancelled = true; };
  }, [countPath]);

  useEffect(() => {
    // 비활성 업체가 낸 지난 발주서도 걸러 볼 수 있게 비활성도 포함한다
    // 업체를 100개씩 끝까지 읽는다 (1,000곳 이상이면 검색형 선택 상자로 바꾸는 것은 후속)
    apiListAll<SupplierOption>("/suppliers?include_inactive=true").then(setSuppliers).catch(setError);
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
  function chooseStatus(value: string) { // 상태 칩: 발주함이 아닌 칩(전체 포함)은 입고 납기를 해제한다
    const next = chipFilter(value, receiptDue);
    list.setPage(1);
    setUrl(next.status, next.receiptDue);
  }
  function chooseDue(value: string) { // 납기 구간을 고르면 발주함만 본다
    list.setPage(1);
    setUrl(value ? "ORDERED" : status, value);
  }

  return (
    <section>
      <div style={S.detailHeader}>
        <h1>발주</h1>
        <ExportButton path="/purchase-orders/export" query={list.exportQuery} summary={list.meta ? `발주서 ${list.meta.total}건(항목 줄 단위로 내보내요)` : null} />
      </div>
      <p><Link href="/purchase-orders/new" style={S.linkButton}>발주서 작성</Link></p>

      <ListControls placeholder="발주번호 검색" onSearch={list.search} />
      <div role="group" aria-label="발주 상태" style={S.chipRow}>{/* 칩이 많으면 다음 줄로 넘어가고 가로 스크롤은 없다 */}
        {[["", "전체"], ...Object.entries(STATUS_LABEL)].map(([code, label]) => {
          const selected = status === code;
          const count = counts ? (code ? counts[code] ?? 0 : Object.values(counts).reduce((a, b) => a + b, 0)) : null; // 전체 = 상태별 합계
          return (
            <button key={code || "ALL"} type="button" aria-pressed={selected} onClick={() => chooseStatus(code)}
              style={{ ...S.statusChip, ...(selected ? S.statusChipSelected : {}) }}>
              {label}{count !== null && <span style={S.statusChipCount}>{count.toLocaleString("ko-KR")}</span>}
            </button>
          );
        })}
      </div>
      <p style={{ margin: "0 0 var(--space-sm)" }}>{/* 미수취 토글: 켜면 입고 기록은 있는데 받은 세금계산서가 없는 발주서만 본다 */}
        <button type="button" aria-pressed={taxMissing} onClick={() => { list.setPage(1); setUrl(status, receiptDue, !taxMissing); }}
          style={{ ...S.statusChip, ...(taxMissing ? S.statusChipSelected : {}) }}>세금계산서 미수취</button>
      </p>
      {receiptDue && ( // 납기 구간이 걸려 있으면 다른 칩 건수가 0인 까닭을 알리고 바로 풀 수 있게 한다
        <p style={S.sub}>{`입고 납기 "${RECEIPT_DUE_LABEL[receiptDue as keyof typeof RECEIPT_DUE_LABEL]}" 적용 중(발주함만 보입니다). `}<button type="button" onClick={() => chooseDue("")} style={{ ...S.detailFilterButton, color: "var(--color-link)", textDecoration: "underline" }}>납기 해제</button></p>
      )}
      <div className="form-compact field-form" style={S.toolbar}>
        <Field label="입고 납기" className="field-half"><select value={receiptDue} onChange={(e) => chooseDue(e.target.value)} style={S.block}>
            <option value="">전체</option>
            {Object.entries(RECEIPT_DUE_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </Field>
        <Field label="공급업체"><select value={supplierId} onChange={(e) => filter(setSupplierId, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </Field>
      </div>
      <ErrorText error={error} />
      <ErrorText error={list.error} />

      <div className="table-box">
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>발주번호</th><th>공급업체</th><th>상태</th><th style={S.num}>품목 수</th><th style={S.num} scope="col">입고 남은 품목</th><th>약속 납기</th></tr>
        </thead>
        <tbody>
          {list.rows.map((o) => { // 각 발주서의 상태와 입고 현황을 한 줄에 표시한다
            const delay = overdueDays(o, today); // 상세와 같은 규칙으로 발주함 상태의 지연 일수를 구한다
            const showReceiptProgress = o.status === "ORDERED" || o.status === "RECEIVED"; // 발주함·입고 완료일 때 입고 현황을 표시한다
            const outstanding = showReceiptProgress ? o.items.filter((item) => remainingQuantity(item) > 0) : [];
            const partialCount = outstanding.filter((item) => item.received_quantity > 0).length; // 부분 입고 품목도 아직 받아야 한다
            return (
              <tr key={o.id} style={S.row}>
                <td style={S.nowrap}><Link href={"/purchase-orders/" + o.id}>{o.po_number}</Link></td>{/* 상세로 가는 링크는 발주번호에만 둔다 */}
                <td>{o.supplier_name}</td>{/* 서버의 공급업체 이름 */}
                <td style={S.nowrap}><PurchaseOrderStatusBadge status={o.status} />{isClosedWithRemainder(o) && <span style={S.sub}>(잔량 마감)</span>}</td>{/* 발주 상태를 글자와 아이콘으로 표시한다 */}
                <td style={S.num}>{o.items.length}</td>{/* 품목 줄 수는 오른쪽 정렬한다 */}
                <td style={S.num}>
                  {showReceiptProgress ? (
                    <>
                      {isClosedWithRemainder(o)
                        ? <strong>마감 {closedTotal(o).toLocaleString("ko-KR")}</strong> /* 입고 완료지만 못 받은 수량을 마감함: 미입고로 보이지 않게 (#252) */
                        : <strong>{outstanding.length.toLocaleString("ko-KR")}개</strong>}
                      {!isClosedWithRemainder(o) && partialCount > 0 && <span style={S.sub}>부분 입고 {partialCount.toLocaleString("ko-KR")}개</span>}
                    </>
                  ) : "—"}
                </td>
                <td style={S.nowrap}>
                  {o.supplier_due_date ?? o.due_date ?? "-"}{/* 회신 납기가 있으면 회신 날짜, 없으면 약속 납기 */}
                  {o.supplier_due_date && <span style={S.sub}>회신</span>}
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
