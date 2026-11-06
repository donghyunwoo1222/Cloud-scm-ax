"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 재고 화면에서 실사 조정으로 이동한다.
import { useSearchParams } from "next/navigation"; // 주소의 ?status= 읽기 (대시보드 링크에서 걸러진 채로 열기)
import { FormEvent, Suspense, useCallback, useEffect, useRef, useState } from "react"; // 폼 제출, 주소 읽는 부품 감싸기, 함수 기억, 처음·변경 시 실행, 즉시 확인용 ref, 상태

import { api, apiList, Meta } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { CHANNEL_LABEL, TYPE_LABEL } from "../../lib/movement-form"; // 유형 이름
import { STOCK_BADGE, StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { quantityLabel } from "../../lib/po"; // 입출고 이력에도 실제 단위를 붙인다.
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일
import { StockTrend } from "./stock-trend"; // 선택한 품목의 30일 마감 재고

// GET /api/v1/stock 의 한 행 (상태는 추천 계산과 같은 기준, #76)
type Stock = {
  product_id: number; sku: string; name: string; unit: string; safety_stock: number; is_active: boolean; current_stock: number;
  reorder_point: number | null; // 서버의 판정 기준
  in_transit: number; // 발주 진행 중(발주함, 미입고) 수량
  status: "SHORTAGE" | "NORMAL" | "UNKNOWN" | null; // 부족·정상·판단 불가 (비활성 품목은 계산하지 않아 null)
  status_reason: { code: string; message: string } | null; // 판단 불가 이유 (예: 데이터 부족)
};
const STATUS_LABEL = { SHORTAGE: "부족", NORMAL: "정상", UNKNOWN: "판단 불가" }; // 상태 코드 → 화면 이름
// GET /api/v1/inventory-movements 의 한 행
type Movement = {
  id: number; product_id: number; product_sku: string | null; product_name: string | null; movement_type: string; direction: "IN" | "OUT";
  quantity: number; movement_date: string; sales_channel: string | null; reason: string | null; memo: string | null;
  product_unit: string | null; correctable_quantity: number | null; // 정정에 표시할 단위와 원본 기준 잔량
  reverses_movement_id: number | null; created_at: string;
};
type ProductOption = { id: number; sku: string; name: string }; // 이력 필터의 품목 선택지

const LABELS = { quantity: "수량", reason: "사유" }; // 정정 오류 details 칸 이름

function focusInView(target: HTMLElement | null, block: ScrollLogicalPosition) {
  if (!target) return;
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  target.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block });
  target.focus({ preventScroll: true }); // 스크롤 위치를 유지하면서 키보드 포커스도 옮긴다
}

// 재고 현황 화면 (주소 /inventory): 품목별 현재고 + 입출고 이력(필터·정정)
// 주소의 ?status= 는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (Next.js 가 빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <Inventory />
    </Suspense>
  );
}

// 주소의 status 를 읽어 목록 부품에 넘긴다. key 를 status 로 주어, 화면이 열린 채(Next.js 가 보관한 화면) 다른 status 링크로 다시 들어와도
// 목록 부품을 새로 만들어 초기값이 다시 적용되게 한다 (useState 초기값은 처음 만들 때 한 번만 쓰인다)
function Inventory() {
  const asked = useSearchParams().get("status") ?? ""; // 주소로 받은 상태 (예: /inventory?status=SHORTAGE → "SHORTAGE")
  const initial = Object.keys(STATUS_LABEL).includes(asked) ? asked : ""; // 허용된 3개만 초기값으로 쓰고 그 밖은 무시("" 이면 전체)
  return <InventoryBody key={initial} initialStatus={initial} />; // status 가 바뀔 때만 새로 만든다 (화면 안에서 필터를 바꾸는 건 주소를 안 바꾸므로 그대로)
}

function InventoryBody({ initialStatus }: { initialStatus: string }) {
  const [status, setStatus] = useState(initialStatus); // 고른 상태 ("" 이면 전체). 처음 값은 주소에서
  const stock = useList<Stock>("/stock", { status, page_size: "10" }); // 상태·검색 결과를 한 쪽에 10품목씩 보여 준다
  const [searchText, setSearchText] = useState(""); // 검색창에 적는 값은 즉시 표시한다
  const { q: appliedSearch, search: searchStock } = stock; // 현재 요청의 검색어와 검색 함수를 가져온다
  const waitingForSearch = searchText.trim() !== appliedSearch; // 입력을 적용하기 전에는 이전 결과를 숨긴다
  const stockReady = !waitingForSearch && stock.isCurrent; // 현재 입력과 조건에 맞는 응답인지 확인한다

  useEffect(() => {
    if (!waitingForSearch) return; // 이미 적용한 검색어면 다시 요청하지 않는다
    const timer = window.setTimeout(() => searchStock(searchText), 300); // 입력이 멈춘 뒤 첫 쪽을 조회한다
    return () => window.clearTimeout(timer); // 다시 입력하거나 화면을 닫으면 이전 타이머를 취소한다
  }, [waitingForSearch, searchStock, searchText]);
  const [historyProduct, setHistoryProduct] = useState<ProductOption>(); // 위 목록에서 선택한 품목
  const productId = historyProduct ? String(historyProduct.id) : ""; // 이력 필터: 품목
  const [trendRevision, setTrendRevision] = useState(0); // 정정 성공 후 같은 품목의 추이도 다시 읽는다
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
  const historyRequest = useRef(0); // 품목 전환 뒤에 도착한 이전 이력 응답은 버린다
  const inventoryTitle = useRef<HTMLHeadingElement>(null); // 선택한 행이 현재 쪽에 없을 때 돌아갈 위치
  const historyTitle = useRef<HTMLHeadingElement>(null); // "입출고 이력" 제목 (이력 보기를 누르면 여기로 이동)
  const selectedHistoryButton = useRef<HTMLButtonElement>(null); // 이력에서 목록으로 돌아갈 때 다시 포커스할 버튼

  const reloadMovements = useCallback(async () => {
    const request = ++historyRequest.current;
    const params = new URLSearchParams({ page: String(page) }); // 쿼리 문자열 (예: page=1&movement_type=SALE)
    if (productId) params.set("product_id", productId);
    if (type) params.set("movement_type", type);
    if (from) params.set("date_from", from);
    if (to) params.set("date_to", to);
    try {
      const r = await apiList<Movement>(`/inventory-movements?${params}`); // 최신순 한 쪽
      if (request !== historyRequest.current) return;
      setRows(r.data); setMeta(r.meta); setError(null);
    } catch (e) {
      if (request === historyRequest.current) setError(e); // 예: 시작일이 종료일보다 늦으면 서버 422 문장
    }
  }, [page, productId, type, from, to]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 이력을 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    reloadMovements(); // 처음 열 때와 쪽·필터가 바뀔 때
    return () => { historyRequest.current += 1; };
  }, [reloadMovements]);

  // 필터를 바꾸면 1쪽부터 다시 본다
  function filter(set: (v: string) => void, value: string) {
    set(value);
    setPage(1);
  }

  function clearHistoryProduct() {
    setHistoryProduct(undefined);
    setRows([]);
    setMeta(null);
    setPage(1);
  }

  // 같은 품목을 다시 누르면 품목 선택을 풀고, 다른 품목을 누르면 해당 이력으로 이동한다.
  function toggleHistory(row: Stock) {
    const selectedId = String(row.product_id);
    if (productId === selectedId) {
      clearHistoryProduct();
      return;
    }
    setHistoryProduct({ id: row.product_id, sku: row.sku, name: row.name });
    setPage(1);
    focusInView(historyTitle.current, "start");
  }

  function returnToInventory() {
    const button = selectedHistoryButton.current; // 선택을 해제하기 전에 돌아갈 행을 잡아 둔다
    clearHistoryProduct();
    focusInView(button ?? inventoryTitle.current, button ? "center" : "start");
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
      setNotice(`정정했습니다. 현재고는 ${quantityLabel(r.stock_after, correcting.product_unit ?? undefined)}입니다.`);
      setCorrecting(null); // 폼 닫기
      setTrendRevision((revision) => revision + 1);
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
      <div style={S.detailHeader}><h1 ref={inventoryTitle} tabIndex={-1}>재고 현황</h1><Link href="/shipments?type=ADJUSTMENT" style={S.linkButtonGhost}>실사 조정</Link></div>
      {/* 기존 목록 검색창과 비활성 포함을 재고 API에 연결한다. */}
      <ListControls placeholder="품목명·SKU 검색" onSearch={searchStock} searchInput={{ value: searchText, onChange: setSearchText, maxLength: 100 }}
        includeInactive={stock.includeInactive} onToggleInactive={stock.toggleInactive}
        tableFilter={(
          <select aria-label="재고 상태" value={status} onChange={(e) => { setStatus(e.target.value); stock.setPage(1); }} style={{ maxWidth: "100%" }}>
            <option value="">전체 상태</option>
            {Object.entries(STATUS_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        )} />
      {stockReady && <ErrorText error={stock.error} />}{/* 현재 조건에서 난 오류만 보여준다. */}
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>품목명</th><th>SKU</th><th style={S.num}>현재고</th><th style={S.num}>발주 진행 중</th><th style={S.num}>안전재고</th><th>상태</th><th></th></tr>
        </thead>
        <tbody>
          {stockReady && !stock.error && stock.rows.map((s) => { // 현재 검색의 결과만 표에 그린다
            const selected = String(s.product_id) === productId; // 아래 추이와 이력이 열린 품목
            return (
            <tr key={s.product_id} style={selected ? { ...bodyRow(s.is_active), ...S.selectedRow } : bodyRow(s.is_active)}>
              <td style={selected ? S.selectedMark : undefined}>{s.name}{!s.is_active && " (비활성)"}</td>
              <td style={S.nowrap}>{s.sku}</td>
              <td style={S.num}>{s.current_stock} {s.unit}</td>
              <td style={S.num}>{quantityLabel(s.in_transit, s.unit)}</td>
              <td style={S.num}>{quantityLabel(s.safety_stock, s.unit)}</td>
              <td title={s.status_reason?.message}>
                {s.status ? <StatusBadge kind={STOCK_BADGE[s.status].kind}>{STOCK_BADGE[s.status].label}</StatusBadge> : "-"}
                {s.status === "SHORTAGE" && s.reorder_point != null && <span style={S.sub}>가용 {quantityLabel(s.current_stock + s.in_transit, s.unit)} · 기준 {quantityLabel(s.reorder_point, s.unit)}</span>}
                {s.status_reason && <span style={S.sub}>{s.status_reason.message}</span>}
                {/* 부족 = 가용재고(현재고 + 발주 진행 중) ≤ 재주문점. 판단 불가는 이유를 작게 보인다. 비활성은 "-" */}
              </td>
              <td>
                <button ref={selected ? selectedHistoryButton : undefined} type="button" aria-expanded={selected} onClick={() => toggleHistory(s)}>
                  {selected ? "추이·이력 닫기" : "추이·이력 보기"}
                </button>
              </td>
              {/* 아래 이력을 이 품목으로 거른다 */}
            </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      {/* 검색 결과가 비면 현재 검색어만 지우고 상태 필터는 유지할 수 있다. */}
      {stockReady && !stock.error && stock.meta?.total === 0 && (
        <div style={S.empty}>
          <p role="status">{appliedSearch ? "검색 조건에 맞는 품목이 없습니다" : status ? "이 상태의 품목이 없습니다." : "품목이 없습니다. 품목을 먼저 등록하세요."}</p>
          {/* 입력칸과 적용한 검색어를 함께 지운다. */}
          {appliedSearch && <button type="button" onClick={() => { setSearchText(""); searchStock(""); }}>검색 지우기</button>}
        </div>
      )}
      <Pager meta={stockReady && !stock.error ? stock.meta : null} onPage={stock.setPage} />{/* 이전 검색의 쪽 번호는 숨긴다. */}

      <div style={{ ...S.detailHeader, marginTop: S.sectionTitle.marginTop, marginBottom: 0 }}>
        <h2 ref={historyTitle} tabIndex={-1} style={{ margin: 0 }}>입출고 이력</h2>
        {productId && <button type="button" onClick={returnToInventory}>접고 목록으로 ↑</button>}
      </div>
      {/* tabIndex -1: 키 이동 순서에는 넣지 않고, 코드로만 포커스를 줄 수 있게 */}
      <p style={S.hint}>{historyProduct
        ? `${historyProduct.name} · ${historyProduct.sku}`
        : "전체 품목의 이력입니다. 특정 품목은 위 목록에서 추이·이력 보기를 누르세요."}</p>
      <div style={S.toolbar}>
        {/* 유형과 기간은 선택한 품목의 이력에 적용한다. */}
        <label>유형
          <select value={type} onChange={(e) => filter(setType, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {Object.entries(TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label>시작일 <input type="date" value={from} onChange={(e) => filter(setFrom, e.target.value)} /></label>
        <label>종료일 <input type="date" value={to} onChange={(e) => filter(setTo, e.target.value)} /></label>
      </div>
      {productId && <StockTrend key={`${productId}:${trendRevision}`} productId={productId} />}
      <ErrorText error={error} />
      {notice && <p role="status" style={S.ok}>{notice}</p>}

      {correcting && (
        <form onSubmit={correct} style={S.panel}>
          {/* 정정 폼: 원래 이력 요약 + 수량·사유 */}
          <span>
            정정 대상: #{correcting.id} {correcting.product_name} {TYPE_LABEL[correcting.movement_type]} {quantityLabel(correcting.quantity, correcting.product_unit ?? undefined)} ({correcting.movement_date})
          </span>
          <label>정정 수량* <input type="number" min={1} max={correcting.correctable_quantity ?? correcting.quantity} step={1}
            aria-describedby="correction-limit" value={cQty} onChange={(e) => setCQty(e.target.value)} />
            <small id="correction-limit">이력 기준 최대 {quantityLabel(correcting.correctable_quantity ?? correcting.quantity, correcting.product_unit ?? undefined)}</small>
          </label>
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
              <td>{m.product_name} <span style={S.nowrap}>({m.product_sku})</span></td>
              <td>{TYPE_LABEL[m.movement_type] ?? m.movement_type}{m.reverses_movement_id !== null && ` (#${m.reverses_movement_id})`}</td>
              {/* 정정 행은 어떤 이력을 바로잡았는지 번호로 보인다 (예: 정정 (#2)) */}
              <td style={S.num}>{m.direction === "IN" ? "+" : "−"}{quantityLabel(m.quantity, m.product_unit ?? undefined)}</td>
              <td>{[m.sales_channel && CHANNEL_LABEL[m.sales_channel], m.reason, m.memo].filter(Boolean).join(" · ")}</td>
              <td>{m.movement_type !== "CORRECTION" && (m.correctable_quantity ?? m.quantity) > 0 && <button type="button" onClick={() => startCorrect(m)}>정정</button>}</td>
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
