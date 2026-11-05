"use client"; // 상태 버튼·입고 폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 목록·수정 화면 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, FormEvent, useCallback, useEffect, useRef, useState } from "react"; // 폼 제출, 함수 기억, 처음 한 번 실행, 즉시 확인용 ref, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { useMe } from "../../../lib/me"; // 내 역할 (승인 버튼은 관리자에게만)
import { seoulToday } from "../../../lib/movement-form"; // 서울 기준 오늘
import { fmtDate, fmtTime, lineAmount, overdueDays, PO_LABELS, PoItemSort, PurchaseOrder, remainingQuantity, totalAmount, visiblePoItems } from "../../../lib/po"; // 발주서 모양·날짜·금액과 표시 품목 계산
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
  const [busy, setBusy] = useState(false); // 입고 등록 중이면 버튼을 잠근다
  const sending = useRef(false); // 아주 빠른 더블클릭을 즉시 막는 표시 (상태값은 늦게 바뀐다)
  const [qty, setQty] = useState<Record<number, string>>({}); // 줄 번호 → 이번 입고 수량 (글자)
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
    const items = Object.entries(qty).filter(([, v]) => v !== "").map(([itemId, v]) => ({ purchase_order_item_id: Number(itemId), quantity: Number(v) })); // 비운 줄은 보내지 않는다
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
  const orderedStatus = order.status === "ORDERED"; // 발주함 상태에서만 품목 표를 거르거나 정렬할 수 있다
  const shownItems = orderedStatus ? visiblePoItems(order.items, itemView.onlyOutstanding, itemView.sort) : order.items; // 화면에 그릴 배열만 가공한다

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

      {/* 발주함 상태의 품목 표에만 조회 조작부를 표시한다. */}
      {orderedStatus && (
        <div style={S.toolbar}>
          {/* 두 필터를 항상 보여주고 입고 폼이 열리면 함께 잠근다. */}
          <fieldset style={S.detailFilterGroup} disabled={receiving}>
            <legend>품목 보기</legend>{/* 키보드와 화면 읽기 도구에서 선택지의 이름을 알 수 있게 한다. */}
            <div style={S.detailFilterOptions}>
              {/* 전체 품목을 고르면 입고 잔량에 관계없이 모든 줄을 보여준다. */}
              <label><input type="radio" name="po-item-view" checked={!itemView.onlyOutstanding} onChange={() => setItemView({ ...itemView, onlyOutstanding: false })} /> 전체 품목</label>
              {/* 미입고만 보기를 고르면 잔량이 있는 줄만 보여준다. */}
              <label><input type="radio" name="po-item-view" checked={itemView.onlyOutstanding} onChange={() => setItemView({ ...itemView, onlyOutstanding: true })} /> 미입고만 보기</label>
            </div>
          </fieldset>
          {/* 정렬 방향도 글자로 표시하고 입고 폼이 열리면 선택을 잠근다. */}
          <label>정렬
            <select style={S.block} disabled={receiving} value={itemView.sort}
              onChange={(event) => setItemView({ ...itemView, sort: event.target.value as PoItemSort })}>
              <option value="registered">등록 순서</option>{/* 서버가 준 순서로 되돌린다. */}
              <option value="name-asc">품목명순 (오름차순)</option>{/* 가나다순으로 나열한다. */}
              <option value="name-desc">품목명순 (내림차순)</option>{/* 가나다의 역순으로 나열한다. */}
            </select>{/* 정렬 선택을 닫는다. */}
          </label>
          {/* 미입고만 볼 때 전체 줄 수와 표시 줄 수를 함께 알린다. */}
          {itemView.onlyOutstanding && <p role="status">전체 {order.items.length}품목 중 {shownItems.length}품목 표시</p>}
        </div>
      )}
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}>
            {/* 수량·단가·금액과 입고 현황을 품목별로 나란히 배치한다. */}
            <th>SKU</th><th>품목</th><th style={S.num}>단가(원)</th><th style={S.num}>발주 수량</th><th style={S.num}>금액(원)</th><th style={S.num}>입고 현황</th>
            {receiving && <th style={S.num}>이번 입고</th>}
          </tr>
        </thead>
        <tbody>
          {/* 필터 결과가 비어도 아래 합계는 전체 품목 기준으로 표시한다. */}
          {orderedStatus && itemView.onlyOutstanding && shownItems.length === 0 && (
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
            return (
              <tr key={i.id} style={S.row}>
                <td style={S.nowrap}>{i.product_sku}</td>
                <td style={S.midCol}>{i.product_name}</td>
                {/* 발주서에 저장된 단가로 이 줄의 발주 금액을 표시한다. */}
                <td style={S.num}>{i.unit_price.toLocaleString("ko-KR")}</td>
                <td style={S.num}>{ordered}{i.unit}</td>
                <td style={S.num}>{lineAmount(i).toLocaleString("ko-KR")}</td>
                <td style={S.num}>
                  {/* 품목마다 실제 단위를 붙여 누적 입고와 남은 수량을 보여준다. */}
                  {remaining === 0 ? "전량 입고" : `${i.received_quantity.toLocaleString("ko-KR")} / ${ordered}${i.unit} 입고 · ${remaining.toLocaleString("ko-KR")}${i.unit} 남음`}
                </td>
                {receiving && (
                  <td style={S.num}><input type="number" style={S.numInput} value={qty[i.id] ?? ""} onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })} aria-label={`${i.product_name} 이번 입고 수량`} /></td>
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
        <form style={S.sectionCard} onSubmit={receive}>
          <p style={S.hint}>품목 표에 이번에 받은 수량을 적으세요. 비워 둔 줄은 입고하지 않습니다.</p>{/* 수량 입력 위치를 알려준다. */}
          {/* 날짜와 버튼은 한 줄에 맞추고 좁은 화면에서는 줄을 바꾼다. */}
          <div style={S.formGrid}>
            {/* 날짜 입력을 짧게 유지하고 미래 날짜는 선택할 수 없게 한다. */}
            <label style={S.receiptDateField}>입고일 <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} /></label>
            {/* 등록과 닫기 버튼은 한 묶음으로 배치한다. */}
            <div style={S.buttons}>
              <button type="submit" disabled={busy}>{busy ? "등록 중…" : "입고"}</button>{/* 전송 중에는 중복 제출을 막는다. */}
              <button type="button" onClick={() => setReceiving(false)}>닫기</button>{/* 폼을 닫아 필터와 정렬을 다시 쓸 수 있게 한다. */}
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
