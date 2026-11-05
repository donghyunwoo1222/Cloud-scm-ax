"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import { FormEvent, useCallback, useEffect, useRef, useState } from "react"; // 폼 제출, 함수 기억, 처음·변경 시 실행, 즉시 확인용 ref, 상태

import { api, apiList, Meta } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { CHANNEL_LABEL, TYPE_LABEL } from "../../lib/movement-form"; // 유형 이름
import { STOCK_BADGE, StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/stock 의 한 행 (상태는 추천 계산과 같은 기준, #76)
type Stock = {
  product_id: number; sku: string; name: string; unit: string; safety_stock: number; is_active: boolean; current_stock: number;
  in_transit: number; // 발주 진행 중(발주함, 미입고) 수량
  status: "SHORTAGE" | "NORMAL" | "UNKNOWN" | null; // 부족·정상·판단 불가 (비활성 품목은 계산하지 않아 null)
  status_reason: { code: string; message: string } | null; // 판단 불가 이유 (예: 데이터 부족)
};
const STATUS_LABEL = { SHORTAGE: "부족", NORMAL: "정상", UNKNOWN: "판단 불가" }; // 상태 코드 → 화면 이름
// GET /api/v1/inventory-movements 의 한 행
type Movement = {
  id: number; product_id: number; product_sku: string | null; product_name: string | null; movement_type: string; direction: "IN" | "OUT";
  quantity: number; movement_date: string; sales_channel: string | null; reason: string | null; memo: string | null;
  reverses_movement_id: number | null; created_at: string;
};
type ProductOption = { id: number; sku: string; name: string }; // 이력 필터의 품목 선택지

const LABELS = { quantity: "수량", reason: "사유" }; // 정정 오류 details 칸 이름

// 재고 현황 화면 (주소 /inventory): 품목별 현재고 + 입출고 이력(필터·정정)
export default function Page() {
  const [status, setStatus] = useState(""); // 재고 목록 상태 필터 ("" 이면 전체)
  const stock = useList<Stock>("/stock", { status }); // 재고 목록 (20개씩, 비활성 포함 선택, 상태로 거르기)
  const [products, setProducts] = useState<ProductOption[]>([]); // 이력 필터의 품목 선택지 (비활성 포함)
  const [productId, setProductId] = useState(""); // 이력 필터: 품목
  const [type, setType] = useState(""); // 이력 필터: 유형
  const [from, setFrom] = useState(""); // 이력 필터: 시작일
  const [to, setTo] = useState(""); // 이력 필터: 종료일
  const [page, setPage] = useState(1); // 이력 쪽
  const [rows, setRows] = useState<Movement[]>([]); // 이력 행
  const [meta, setMeta] = useState<Meta | null>(null); // 이력 쪽 정보
  const [error, setError] = useState<unknown>(null); // 이력 불러오기 오류
  const [correcting, setCorrecting] = useState<Movement | null>(null); // 정정 중인 이력
  const [cQty, setCQty] = useState(""); // 정정 수량
  const [cReason, setCReason] = useState(""); // 정정 사유
  const [cError, setCError] = useState<unknown>(null); // 정정 오류
  const [notice, setNotice] = useState(""); // 정정 성공 안내
  const [busy, setBusy] = useState(false); // 정정 등록 중이면 버튼을 잠근다
  const sending = useRef(false); // 아주 빠른 더블클릭을 즉시 막는 표시 (상태값은 늦게 바뀐다)
  const historyTitle = useRef<HTMLHeadingElement>(null); // "입출고 이력" 제목 (이력 보기를 누르면 여기로 이동)

  useEffect(() => {
    // shortcut: 품목 100개까지만 선택지로 불러온다(서버 page_size 최대). 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<ProductOption>("/products?page_size=100&include_inactive=true").then((r) => setProducts(r.data)).catch(setError);
  }, []);

  const reloadMovements = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page) }); // 쿼리 문자열 (예: page=1&movement_type=SALE)
    if (productId) params.set("product_id", productId);
    if (type) params.set("movement_type", type);
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    try {
      const r = await apiList<Movement>(`/inventory-movements?${params}`); // 최신순 한 쪽
      setRows(r.data); setMeta(r.meta); setError(null);
    } catch (e) {
      setError(e); // 예: 시작일이 종료일보다 늦으면 서버 422 문장
    }
  }, [page, productId, type, from, to]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 이력을 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    reloadMovements(); // 처음 열 때와 쪽·필터가 바뀔 때
  }, [reloadMovements]);

  // 필터를 바꾸면 1쪽부터 다시 본다
  function filter(set: (v: string) => void, value: string) {
    set(value);
    setPage(1);
  }

  // 이 품목의 이력 보기: 이력을 품목으로 거르고 "입출고 이력" 제목으로 화면과 포커스를 옮긴다
  function showHistory(id: number) {
    filter(setProductId, String(id));
    const title = historyTitle.current;
    if (!title) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; // OS 의 "움직임 줄이기" 설정이 켜져 있으면 스르륵 대신 바로 이동
    title.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" }); // 아래로 스르륵 내려간다
    title.focus({ preventScroll: true }); // 키보드·낭독기 사용자도 이력 영역으로 따라오게 (스크롤은 위에서 이미 했다)
  }

  function startCorrect(m: Movement) {
    setCorrecting(m); setCQty(""); setCReason(""); setCError(null); setNotice(""); // 폼 열기 (이전 입력 비움)
  }

  async function correct(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    if (!correcting || sending.current) return; // 정정 대상이 없거나 이미 등록 중이면 버린다
    sending.current = true; // 즉시 잠금
    setBusy(true); // 버튼 잠금·글자 변경
    try {
      const r = await api<{ stock_after: number }>(`/inventory-movements/${correcting.id}/corrections`, {
        method: "POST", body: { quantity: cQty === "" ? null : Number(cQty), reason: cReason }, // 1 이상 정수·사유 필수 검사는 서버가
      });
      setNotice(`정정했습니다. 현재고는 ${r.stock_after}개입니다.`);
      setCorrecting(null); // 폼 닫기
      await Promise.all([reloadMovements(), stock.reload()]); // 이력·재고 숫자 다시 불러오기
    } catch (e) {
      setCError(e); // 폼은 열어 둔 채 입력값 유지. 서버 문장 그대로 (정정 수량 초과, 재고 부족 등)
    } finally {
      sending.current = false; // 성공·실패 모두 다시 누를 수 있게 푼다
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>재고 현황</h1>
      <ListControls includeInactive={stock.includeInactive} onToggleInactive={stock.toggleInactive} />
      {/* 재고 목록 API 에는 검색어가 없어 검색창은 숨긴다 */}
      <div style={S.toolbar}>
        <label>상태
          <select value={status} onChange={(e) => { setStatus(e.target.value); stock.setPage(1); }} style={S.block}>
            <option value="">전체</option>
            {Object.entries(STATUS_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        {/* 상태를 고르면 서버가 회사 전체에서 거른 뒤 쪽을 나눈다. 비활성 품목은 상태가 없어 나오지 않는다 */}
      </div>
      <ErrorText error={stock.error} />
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>품목명</th><th>SKU</th><th style={S.num}>현재고</th><th style={S.num}>발주 진행 중</th><th style={S.num}>안전재고</th><th>상태</th><th></th></tr>
        </thead>
        <tbody>
          {stock.rows.map((s) => (
            <tr key={s.product_id} style={bodyRow(s.is_active)}>
              <td>{s.name}{!s.is_active && " (비활성)"}</td>
              <td>{s.sku}</td>
              <td style={S.num}>{s.current_stock} {s.unit}</td>
              <td style={S.num}>{s.in_transit}</td>
              <td style={S.num}>{s.safety_stock}</td>
              <td title={s.status_reason?.message}>
                {s.status ? <StatusBadge kind={STOCK_BADGE[s.status].kind}>{STOCK_BADGE[s.status].label}</StatusBadge> : "-"}
                {s.status_reason && <span style={S.sub}>{s.status_reason.message}</span>}
                {/* 부족 = 가용재고(현재고 + 발주 진행 중) ≤ 재주문점. 판단 불가는 이유를 작게 보인다. 비활성은 "-" */}
              </td>
              <td><button type="button" onClick={() => showHistory(s.product_id)}>이력 보기</button></td>
              {/* 아래 이력을 이 품목으로 거른다 */}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {stock.meta?.total === 0 && <p style={S.empty}>{status ? "이 상태의 품목이 없습니다." : "품목이 없습니다. 품목을 먼저 등록하세요."}</p>}
      <Pager meta={stock.meta} onPage={stock.setPage} />

      <h2 ref={historyTitle} tabIndex={-1} style={S.sectionTitle}>입출고 이력</h2>
      {/* tabIndex -1: 키 이동 순서에는 넣지 않고, 코드로만 포커스를 줄 수 있게 */}
      <div style={S.toolbar}>
        {/* 필터: 품목·유형·기간 */}
        <label>품목
          <select value={productId} onChange={(e) => filter(setProductId, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
          </select>
        </label>
        <label>유형
          <select value={type} onChange={(e) => filter(setType, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>시작일 <input type="date" value={from} onChange={(e) => filter(setFrom, e.target.value)} /></label>
        <label>종료일 <input type="date" value={to} onChange={(e) => filter(setTo, e.target.value)} /></label>
      </div>
      <ErrorText error={error} />
      {notice && <p role="status" style={S.ok}>{notice}</p>}

      {correcting && (
        <form onSubmit={correct} style={S.panel}>
          {/* 정정 폼: 원래 이력 요약 + 수량·사유 */}
          <span>
            정정 대상: #{correcting.id} {correcting.product_name} {TYPE_LABEL[correcting.movement_type]} {correcting.quantity}개 ({correcting.movement_date})
          </span>
          <label>정정 수량* <input type="number" min={1} step={1} value={cQty} onChange={(e) => setCQty(e.target.value)} /></label>
          <label>사유* <input value={cReason} onChange={(e) => setCReason(e.target.value)} placeholder="예: 10개를 100개로 잘못 입력" /></label>
          <button type="submit" disabled={busy}>{busy ? "등록 중…" : "정정 등록"}</button>
          <button type="button" onClick={() => setCorrecting(null)}>취소</button>
          <div style={S.basisFull}><ErrorText error={cError} labels={LABELS} /></div>
        </form>
      )}

      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>번호</th><th>입출고일</th><th>품목</th><th>유형</th><th style={S.num}>수량</th><th>사유·채널·메모</th><th></th></tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m.id} style={S.row}>
              <td>#{m.id}</td>
              <td style={S.nowrap}>{m.movement_date}</td>
              <td>{m.product_name} ({m.product_sku})</td>
              <td>{TYPE_LABEL[m.movement_type] ?? m.movement_type}{m.reverses_movement_id !== null && ` (#${m.reverses_movement_id})`}</td>
              {/* 정정 행은 어떤 이력을 바로잡았는지 번호로 보인다 (예: 정정 (#2)) */}
              <td style={S.num}>{m.direction === "IN" ? "+" : "−"}{m.quantity}</td>
              <td>{[m.sales_channel && CHANNEL_LABEL[m.sales_channel], m.reason, m.memo].filter(Boolean).join(" · ")}</td>
              <td>{m.movement_type !== "CORRECTION" && <button type="button" onClick={() => startCorrect(m)}>정정</button>}</td>
              {/* 정정 행에는 버튼을 숨긴다 (정정의 정정 금지) */}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {meta?.total === 0 && <p style={S.empty}>조건에 맞는 이력이 없습니다.</p>}
      <Pager meta={meta} onPage={setPage} />
    </section>
  );
}
