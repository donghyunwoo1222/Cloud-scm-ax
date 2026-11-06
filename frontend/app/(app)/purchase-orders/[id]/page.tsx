"use client"; // 상태 버튼·입고 폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 목록·수정 화면 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, FormEvent, useCallback, useEffect, useId, useRef, useState } from "react"; // 폼 제출, 연결용 ID, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { useMe } from "../../../lib/me"; // 내 역할 (승인 버튼은 관리자에게만)
import { seoulToday } from "../../../lib/movement-form"; // 서울 기준 오늘
import { boxLimit, fmtDate, fmtTime, formatOrderUnitPrice, lineAmount, MAX_ORDER_QUANTITY, overdueDays, PO_LABELS, PoItemSort, PurchaseOrder, quantityLabel, remainingQuantity, totalAmount, visiblePoItems } from "../../../lib/po"; // 발주서 모양·날짜·금액과 박스 환산
import { PurchaseOrderStatusBadge, StatusBadge } from "../../../lib/status-badge"; // 공통 발주 상태와 납기 지연 배지
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// 상태별로 누를 수 있는 버튼: [서버 동사 경로, 버튼 이름]. 승인은 관리자만 (서버도 403 으로 막는다)
const ACTIONS: Record<string, [string, string][]> = {
  DRAFT: [["approve", "승인"], ["cancel", "취소"]],
  APPROVED: [["order", "발주함 표시"], ["cancel", "취소"]],
  ORDERED: [["cancel", "취소"]], // 입고 등록은 아래 폼 여는 버튼이 따로 있다
};

const DEFAULT_ITEM_VIEW = { onlyOutstanding: false, sort: "registered" as PoItemSort }; // 전체 품목과 등록 순서가 기본값이다

// 발주서 상세 화면 (주소 /purchase-orders/번호)
function Detail() {
  const { id } = useParams<{ id: string }>(); // 주소의 발주서 번호
  const me = useMe(); // 내 정보 (확인 전 null)
  const [order, setOrder] = useState<PurchaseOrder | null>(null); // 불러온 발주서
  const [error, setError] = useState<unknown>(null); // 불러오기·버튼·입고 오류
  const [notice, setNotice] = useState(""); // 성공 안내 문장
  const [receiving, setReceiving] = useState(false); // 입고 등록 폼을 열었는지
  const receiptFormId = useId(); // 표 안의 입력을 이 발주서의 폼에 연결한다
  const [busy, setBusy] = useState(false); // 입고 등록 중이면 버튼을 잠근다
  const sending = useRef(false); // 아주 빠른 더블클릭을 즉시 막는 표시 (상태값은 늦게 바뀐다)
  const [qty, setQty] = useState<Record<number, { value: string; box: boolean }>>({}); // 줄 번호 → 이번 입고 수량과 단위
  const [date, setDate] = useState(""); // 입고일 (화면이 열린 뒤 서울 오늘로 채운다)
  const [today, setToday] = useState(""); // 입고일 상한 (미래 날짜 선택 불가)
  const [itemView, setItemView] = useState({ scope: "", ...DEFAULT_ITEM_VIEW }); // 발주서와 상태별로 표의 선택을 기억한다

  const load = useCallback(async () => {
    try {
      setOrder(await api<PurchaseOrder>(`/purchase-orders/${id}`)); // 서버에서 발주서 한 건
    } catch (e) {
      setError(e);
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    load(); // 처음 열 때
    const t = seoulToday(); // 서버 렌더링 때 시각을 읽으면 빌드가 막혀 화면이 열린 뒤 채운다
    setToday(t); setDate(t); // 상한과 기본값
  }, [load]);

  const itemViewScope = order ? `${order.id}:${order.status}` : ""; // 같은 발주서가 같은 상태로 다시 오면 같은 범위다
  if (itemView.scope !== itemViewScope) { // 발주서나 상태가 바뀌는 렌더에서만 선택을 초기화한다
    setItemView({ scope: itemViewScope, ...DEFAULT_ITEM_VIEW }); // 부분 입고 응답은 발주함 상태라 선택을 유지한다
  } // 같은 범위에서는 사용자의 선택을 유지한다

  // 승인·발주함 표시·취소: 바뀐 발주서를 돌려받아 화면에 반영한다
  async function act(action: string) {
    if (action === "cancel" && !window.confirm("이 발주서를 취소할까요? 되돌릴 수 없습니다.")) return; // 취소는 한 번 더 확인
    try {
      setOrder(await api<PurchaseOrder>(`/purchase-orders/${id}/${action}`, { method: "POST" })); // 서버가 한 단계만 바꾼다
      setError(null); // 이전 오류 지우기
      setNotice("");
      setReceiving(false);
      setQty({});
    } catch (e) {
      setError(e); // 서버 문장 그대로 (INVALID_STATUS, CANNOT_CANCEL_RECEIVED, INACTIVE_REFERENCE 등)
      load(); // 다른 사람이 먼저 바꿨을 수 있으니 최신 상태로 다시 불러온다
    }
  }

  // 입고 등록: 수량을 적은 줄만 한 번에 보낸다 (하나라도 넘치면 서버가 아무것도 저장하지 않는다)
  async function receive(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    if (sending.current) return; // 이미 등록 중이면 두 번째 제출은 버린다
    sending.current = true; // 즉시 잠금
    setBusy(true); // 버튼 잠금·글자 변경
    const items = Object.entries(qty).filter(([, entry]) => entry.value !== "").map(([itemId, entry]) => ({
      purchase_order_item_id: Number(itemId),
      ...(entry.box ? { box_quantity: Number(entry.value) } : { quantity: Number(entry.value) }),
    })); // 비운 줄은 보내지 않는다
    try {
      setOrder(await api<PurchaseOrder>(`/purchase-orders/${id}/receipts`, { method: "POST", body: { movement_date: date || null, items } })); // 서버가 입고 이력을 쌓고 상태도 바꾼다
      setError(null);
      setQty({}); // 성공했을 때만 입력값을 비운다
      setReceiving(false);
      setNotice("입고했습니다. 입고한 수량만큼 현재고가 늘었습니다.");
    } catch (e) {
      setError(e); // 서버 문장 그대로 (OVER_RECEIPT 는 남은 수량이 들어 있다). 입력값은 지우지 않는다
    } finally {
      sending.current = false; // 성공·실패 모두 다시 누를 수 있게 푼다
      setBusy(false);
    }
  }

  if (!order) return <section><h1>발주서</h1><ErrorText error={error} /></section>; // 불러오기 전·실패

  const buttons = (ACTIONS[order.status] ?? []).filter(([action]) => action !== "approve" || me?.role === "ADMIN"); // 담당자에게는 승인 버튼을 숨긴다
  const staffDraft = order.status === "DRAFT" && me?.role !== "ADMIN"; // 담당자가 본 작성 중 발주서
  const delay = overdueDays(order, today); // 입고일에 쓰는 서울 오늘 날짜로 납기 지연도 판단한다
  const orderedStatus = order.status === "ORDERED"; // 발주함 상태에서만 미입고 필터를 보여준다
  const isFiltered = orderedStatus && itemView.onlyOutstanding; // 미입고 필터는 발주함 상태에서만 적용한다
  const shownItems = visiblePoItems(order.items, isFiltered, itemView.sort); // 모든 상태에서 표에 그릴 배열만 정렬한다

  return (
    <section>
      <header style={S.detailHeader}>
        {/* 발주번호와 상태는 제목 줄에 함께 보여준다. */}
        <div style={S.detailTitle}>
          <h1 style={{ margin: 0 }}>발주서 {order.po_number}</h1>
          <PurchaseOrderStatusBadge status={order.status} />
        </div>
        <Link href="/purchase-orders" style={S.linkButtonGhost}>발주 목록</Link>
      </header>
      <div style={S.card}>
        {/* 공급업체와 약속 납기를 항목 이름과 값으로 읽을 수 있게 묶는다. */}
        <dl style={S.detailFacts}>
          <div>
            <dt style={S.detailLabel}>공급업체</dt>
            <dd style={S.detailValue}><Link href={`/suppliers/${order.supplier_id}`}>{order.supplier_name}</Link></dd>
          </div>
          <div>
            <dt style={S.detailLabel}>약속 납기</dt>
            <dd style={{ ...S.detailValue, ...S.detailTitle }}>
              {order.due_date ?? "납기 미정"}{/* 약속한 날짜가 없으면 미정으로 표시한다. */}
              {delay > 0 && <StatusBadge kind="danger">납기 {delay.toLocaleString("ko-KR")}일 지연</StatusBadge>}
            </dd>
          </div>
        </dl>
        {/* 상태 기록은 항목명과 날짜를 칸으로 나누고 메모는 별도 줄에 둔다. */}
        <div style={S.detailMeta}>
          <dl style={S.detailHistory}>
            {/* 각 기록은 좁은 화면에서도 제목과 날짜가 같은 칸에 남는다. */}
            <div style={S.detailHistoryCell}>
              <dt>승인</dt>
              <dd style={S.detailHistoryValue}>{fmtTime(order.approved_at)}</dd>
            </div>
            <div style={S.detailHistoryCell}>
              <dt>발주함 표시</dt>
              <dd style={S.detailHistoryValue}>{fmtTime(order.ordered_at)}</dd>
            </div>
            <div style={S.detailHistoryCell}>
              <dt>실제 입고일</dt>
              <dd style={S.detailHistoryValue}>{fmtDate(order.received_at)}</dd>
            </div>
            {order.cancelled_at && (
              <div style={S.detailHistoryCell}>
                <dt>취소</dt>
                <dd style={S.detailHistoryValue}>{fmtTime(order.cancelled_at)}</dd>
              </div>
            )}
          </dl>
          <dl style={S.detailMemo}>
            <dt>메모</dt>
            <dd style={S.detailHistoryValue}>{order.memo ?? "-"}</dd>
          </dl>
        </div>
      </div>

      {/* 모든 상태의 품목 표에 같은 정렬 조작부를 표시한다. */}
      <div style={S.tableToolbar}>{/* 품목 표들과 같은 도구막대 스타일을 사용한다. */}
        {/* 발주함 상태에서는 필터 두 개를 붙이고 눌린 상태를 화면 읽기 도구에도 전달한다. */}
        {orderedStatus && (
          <div role="group" aria-label="품목 보기" style={S.detailFilterGroup}>
            {[false, true].map((onlyOutstanding) => { // 전체 품목과 미입고만 보기 버튼을 차례로 만든다
              const selected = itemView.onlyOutstanding === onlyOutstanding; // 현재 보기와 일치하는 버튼만 선택 상태다
              return (
                // 입고 폼을 열면 필터를 잠그고 선택 표시는 유지한다.
                <button key={String(onlyOutstanding)} type="button" disabled={receiving} aria-pressed={selected}
                  style={{ ...S.detailFilterButton, ...(selected ? S.detailFilterSelected : {}) }}
                  onClick={() => setItemView({ ...itemView, onlyOutstanding })}>
                  {/* 선택한 쪽만 체크를 보여 주되 두 버튼의 폭은 유지한다. */}
                  <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none" style={{ visibility: selected ? "visible" : "hidden" }}>
                    <path d="m3 8 3 3 7-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  {onlyOutstanding ? "미입고만 보기" : "전체 품목"}{/* 각 필터가 무엇을 보여주는지 글자로 표시한다. */}
                </button>
              ); // 필터 버튼 하나를 반환한다
            })}
          </div>
        )}
        {/* 정렬 상자는 선택지에 필요한 너비만 차지하고 입고 중에는 잠긴다. */}
        <select aria-label="품목 정렬" style={{ maxWidth: "100%" }} disabled={receiving} value={itemView.sort}
          onChange={(event) => setItemView({ ...itemView, sort: event.target.value as PoItemSort })}>
          <option value="registered">등록 순서</option>{/* 서버가 준 순서로 되돌린다. */}
          <option value="name-asc">품목명순 (오름차순)</option>{/* 가나다순으로 나열한다. */}
          <option value="name-desc">품목명순 (내림차순)</option>{/* 가나다의 역순으로 나열한다. */}
        </select>
        {/* 미입고만 볼 때 전체 줄 수와 표시 줄 수를 함께 알린다. */}
        {isFiltered && <p role="status" style={S.detailTableCount}>전체 {order.items.length}품목 중 {shownItems.length}품목 표시</p>}
      </div>
      <div style={S.tableBox}>
      {/* 표 윗여백을 없애 조작부와 붙인다. */}
      <table style={{ ...S.table, marginTop: 0 }}>
        <thead>
          <tr style={S.headRow}>
            {/* 수량·단가·금액과 입고 현황을 품목별로 나란히 배치한다. */}
            <th>SKU</th><th>품목</th><th style={S.num}>단가(원)</th><th style={S.num}>발주 수량</th><th style={S.num}>금액(원)</th><th style={S.num}>입고 현황</th>
            {receiving && <th style={S.num}>이번 입고</th>}
          </tr>
        </thead>
        <tbody>
          {/* 필터 결과가 비어도 아래 합계는 전체 품목 기준으로 표시한다. */}
          {isFiltered && shownItems.length === 0 && (
            <tr>
              <td colSpan={receiving ? 7 : 6} style={S.empty}>
                <p>조건에 맞는 품목이 없습니다.</p>{/* 미입고 필터 결과가 없음을 알린다. */}
                {/* 다른 전환과 같이 입고 폼을 닫은 뒤 필터를 해제할 수 있다. */}
                <button type="button" disabled={receiving} onClick={() => setItemView({ ...itemView, onlyOutstanding: false })}>필터 해제</button>
              </td>
            </tr>
          )}
          {shownItems.map((i) => { // 표시할 행만 그리며 입고 입력은 기존대로 발주 품목 ID에 연결한다
            const remaining = remainingQuantity(i); // 필터와 같은 기준으로 입고 잔량을 구한다
            const ordered = i.quantity.toLocaleString("ko-KR"); // 발주 수량과 입고 현황에 같은 쉼표 표기를 쓴다
            const units = i.units_per_box; // 발주 당시의 입수로 입고 수량을 환산한다
            const maxBoxes = units != null ? boxLimit(units, remaining) : 0;
            const entry = qty[i.id];
            const byBox = entry?.box ?? (maxBoxes > 0);
            return (
              <tr key={i.id} style={S.row}>
                <td style={S.nowrap}>{i.product_sku}</td>
                <td style={S.midCol}>{i.product_name}</td>
                {/* 발주서에 저장된 단가로 이 줄의 발주 금액을 표시한다. */}
                <td style={S.num}>{formatOrderUnitPrice(i)}</td>
                <td style={S.num}>
                  {i.box_quantity == null ? `${ordered}${i.unit}` : (
                    <>{quantityLabel(i.box_quantity, "박스")}<span style={S.sub}>재고 {ordered}{i.unit}</span></>
                  )}
                </td>
                <td style={S.num}>{lineAmount(i).toLocaleString("ko-KR")}</td>
                <td style={S.num}>
                  {/* 품목마다 실제 단위를 붙여 누적 입고와 남은 수량을 보여준다. */}
                  {remaining === 0 ? "전량 입고" : `${i.received_quantity.toLocaleString("ko-KR")} / ${ordered}${i.unit} 입고 · ${remaining.toLocaleString("ko-KR")}${i.unit} 남음`}
                </td>
                {receiving && (
                  <td style={S.num}>{remaining > 0 && (
                    <>
                      {maxBoxes > 0 && (
                        <select value={byBox ? "box" : "stock"} disabled={busy} aria-label={`${i.product_name} 입고 단위`}
                          onChange={(e) => setQty({ ...qty, [i.id]: { value: "", box: e.target.value === "box" } })}>
                          <option value="box">박스</option>
                          <option value="stock">재고 단위 ({i.unit})</option>
                        </select>
                      )}{" "}
                      <input type="number" form={receiptFormId} min={1} max={byBox ? maxBoxes : Math.min(remaining, MAX_ORDER_QUANTITY)} step={1}
                        style={S.numInput} value={entry?.value ?? ""} disabled={busy}
                        onChange={(e) => setQty({ ...qty, [i.id]: { value: e.target.value, box: byBox } })}
                        aria-label={`${i.product_name} 이번 입고 ${byBox ? "박스 수" : "수량"}`} />
                      {byBox && units != null && <span style={S.sub}>
                        {entry?.value ? `재고 ${quantityLabel(Number(entry.value) * units, i.unit)}` : `1박스 · 재고 ${quantityLabel(units, i.unit)}`}
                      </span>}
                    </>
                  )}</td>
                )}
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          {/* 합계는 모든 품목을 포함하며, 각 줄의 금액과 같은 열에 맞춘다. */}
          <tr>
            <th scope="row" colSpan={4} style={S.num}>발주 금액 합계</th>
            <td style={{ ...S.num, ...S.key }}>{totalAmount(order).toLocaleString("ko-KR")}원</td>
            <td colSpan={receiving ? 2 : 1} />
          </tr>
        </tfoot>
      </table>
      </div>

      <p style={S.buttons}>
        {order.status === "DRAFT" && <Link href={`/purchase-orders/${order.id}/edit`} style={S.linkButtonGhost}>수정</Link>}
        {/* 작성 중일 때만 수정 화면으로 간다 */}
        {buttons.map(([action, label]) => <button key={action} type="button" onClick={() => act(action)}>{label}</button>)}
        {order.status === "ORDERED" && !receiving && <button type="button" onClick={() => setReceiving(true)}>입고 등록</button>}
      </p>
      {staffDraft && <p>승인은 관리자만 할 수 있습니다. 관리자에게 승인을 요청하세요.</p>}
      {/* 서버도 403 으로 막지만 화면에서도 안내한다 */}

      {receiving && (
        // 취소 등 발주서 버튼과 입고 폼을 카드로 구분한다.
        <form id={receiptFormId} style={S.sectionCard} onSubmit={receive}>
          <p style={S.hint}>품목 표에 이번에 받은 수량을 적으세요. 비워 둔 줄은 입고하지 않습니다.</p>{/* 수량 입력 위치를 알려준다. */}
          {/* 날짜와 버튼은 한 줄에 맞추고 좁은 화면에서는 줄을 바꾼다. */}
          <div style={S.formGrid}>
            {/* 날짜 입력을 짧게 유지하고 미래 날짜는 선택할 수 없게 한다. */}
            <label style={S.receiptDateField}>입고일 <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} /></label>
            {/* 등록과 닫기 버튼은 한 묶음으로 배치한다. */}
            <div style={S.buttons}>
              <button type="submit" disabled={busy}>{busy ? "등록 중…" : "입고"}</button>{/* 전송 중에는 중복 제출을 막는다. */}
              <button type="button" disabled={busy} onClick={() => { setReceiving(false); setQty({}); }}>닫기</button>{/* 숨긴 줄의 입력값이 다음 입고에 섞이지 않게 비운다. */}
            </div>
          </div>
        </form>
      )}
      {notice && <p role="status" style={S.ok}>{notice}</p>}
      <ErrorText error={error} labels={PO_LABELS} />
    </section>
  );
}

// 주소의 번호는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (Next.js 가 빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <Detail />
    </Suspense>
  );
}
