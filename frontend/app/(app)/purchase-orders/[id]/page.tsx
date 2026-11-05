"use client"; // 상태 버튼·입고 폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 목록·수정 화면 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, FormEvent, useCallback, useEffect, useRef, useState } from "react"; // 폼 제출, 함수 기억, 처음 한 번 실행, 즉시 확인용 ref, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { useMe } from "../../../lib/me"; // 내 역할 (승인 버튼은 관리자에게만)
import { seoulToday } from "../../../lib/movement-form"; // 서울 기준 오늘
import { fmtDate, fmtTime, PO_LABELS, PurchaseOrder, STATUS_LABEL } from "../../../lib/po"; // 발주서 모양·이름·시각 표시
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// 상태별로 누를 수 있는 버튼: [서버 동사 경로, 버튼 이름]. 승인은 관리자만 (서버도 403 으로 막는다)
const ACTIONS: Record<string, [string, string][]> = {
  DRAFT: [["approve", "승인"], ["cancel", "취소"]],
  APPROVED: [["order", "발주함 표시"], ["cancel", "취소"]],
  ORDERED: [["cancel", "취소"]], // 입고 등록은 아래 폼 여는 버튼이 따로 있다
};

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

  return (
    <section>
      <h1>발주서 {order.po_number}</h1>
      <p><Link href="/purchase-orders">목록</Link></p>
      <p>공급업체: <Link href={`/suppliers/${order.supplier_id}`}>{order.supplier_name}</Link> · 상태: {STATUS_LABEL[order.status]} · 약속 납기: {order.due_date ?? "-"}</p>
      <p>메모: {order.memo ?? "-"}</p>
      <p>승인: {fmtTime(order.approved_at)} · 발주함 표시: {fmtTime(order.ordered_at)} · 입고 완료(실제 입고일): {fmtDate(order.received_at)}</p>
      {order.cancelled_at && <p>취소: {fmtTime(order.cancelled_at)}</p>}

      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}>
            <th>SKU</th><th>품목</th><th style={S.num}>단가(원)</th><th style={S.num}>발주 수량</th><th style={S.num}>누적 입고량</th><th style={S.num}>남은 수량</th>
            {receiving && <th style={S.num}>이번 입고</th>}
          </tr>
        </thead>
        <tbody>
          {order.items.map((i) => (
            <tr key={i.id} style={S.row}>
              <td>{i.product_sku}</td>
              <td>{i.product_name}</td>
              <td style={S.num}>{i.unit_price}</td>
              <td style={S.num}>{i.quantity}</td>
              <td style={S.num}>{i.received_quantity}</td>
              <td style={S.num}>{i.quantity - i.received_quantity}</td>
              {receiving && (
                <td style={S.num}><input type="number" style={S.numInput} value={qty[i.id] ?? ""} onChange={(e) => setQty({ ...qty, [i.id]: e.target.value })} aria-label={`${i.product_name} 이번 입고 수량`} /></td>
              )}
            </tr>
          ))}
        </tbody>
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
        <form onSubmit={receive}>
          <p>줄마다 이번에 들어온 수량을 적으세요(비운 줄은 입고하지 않습니다). 입고하면 그 수량만큼 현재고가 늘어납니다.</p>
          <label>입고일 <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value)} /></label>
          {/* 미래 날짜는 고를 수 없다 (서버도 422) */}
          <p style={S.buttons}>
            <button type="submit" disabled={busy}>{busy ? "등록 중…" : "입고"}</button>
            <button type="button" onClick={() => setReceiving(false)}>닫기</button>
          </p>
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
