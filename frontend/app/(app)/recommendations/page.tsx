"use client"; // 체크·수량 입력·버튼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주서 상세 링크
import { useSearchParams } from "next/navigation"; // 대시보드에서 선택한 품목 번호
import { Fragment, Suspense, useCallback, useEffect, useRef, useState } from "react"; // 주소를 읽는 화면과 추천 상태

import { ApiError, api, apiList } from "../../lib/api"; // 공통 API 호출 함수·오류 종류
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { boxLimit, MAX_ORDER_QUANTITY, PO_LABELS, PoItem, PurchaseOrder, quantityLabel } from "../../lib/po"; // 발주서와 박스 환산 표시
import { StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S } from "../../lib/styles"; // 화면 공통 스타일
import styles from "./page.module.css"; // 추천 화면 근거 버튼 스타일

// GET /api/v1/recommendations 응답의 추천 한 줄 (backend/app/services/recommendations.py)
type Item = {
  product_id: number; product_sku: string; product_name: string; // 품목
  supplier_id: number; supplier_name: string; unit: string; // 기본 공급업체
  current_stock: number; in_transit: number; available: number; // 현재고, 발주 진행 중, 가용재고(= 둘의 합)
  avg_daily_sales: number; lead_time_days: number; safety_stock: number; // 일평균(소수), 리드타임, 안전재고
  reorder_point: number; recommended_quantity: number; reason: string; // 재주문점(소수), 추천 수량, 이유 문구
  units_per_box: number | null; recommended_box_quantity: number | null; // 현재 입수와 서버가 올림한 기본 박스 수
};
type Excluded = { product_id: number; product_sku: string; product_name: string; message: string }; // 서버가 제외 사유 문장까지 내려준다
type Draft = { id: number; po_number: string } & Pick<PoItem, "quantity" | "box_quantity" | "unit">;
type Created = PurchaseOrder & { created: boolean }; // 초안 만들기 응답 한 장 (created: 새로 만들었는지)

const REASON_TEXT: Record<string, string> = {
  ENOUGH_STOCK: "지금은 재고가 충분합니다", INSUFFICIENT_DATA: "기록이 14일이 안 됩니다", NO_SALES_30D: "최근 30일 판매가 없습니다",
}; // NOT_RECOMMENDED 의 품목별 사유 → 문장
const MAX_ITEMS = 100; // 한 요청에 보낼 수 있는 품목 수 (서버 상한)

// 소수는 첫째 자리까지, 정수는 그대로 (예: 0.2333 → "0.2", 70 → "70"). 서버 이유 문구와 같은 방식
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));

// 발주 추천 화면 (주소 /recommendations): 추천 목록 → 체크·수량 수정 → 발주서 초안 만들기
export default function Page() {
  return <Suspense fallback={<section><h1>발주 추천</h1><p>불러오는 중…</p></section>}><RecommendationRoute /></Suspense>;
}

function RecommendationRoute() {
  const param = useSearchParams().get("product_id");
  const parsed = Number(param);
  const productId = param && /^[1-9]\d*$/.test(param) && Number.isSafeInteger(parsed) ? parsed : null;
  return <Recommendations key={productId ?? "all"} productId={productId} />; // 다른 품목을 열면 선택·입력 상태도 새로 시작한다
}

function Recommendations({ productId }: { productId: number | null }) {
  const [items, setItems] = useState<Item[] | null>(null); // 추천 목록 (불러오기 전 null)
  const [excluded, setExcluded] = useState<Excluded[]>([]); // 제외된 품목
  const [drafts, setDrafts] = useState<Record<number, Draft>>({}); // 품목 id → 그 품목이 든 작성 중 발주서
  const [loadError, setLoadError] = useState<unknown>(null); // 목록 불러오기 오류
  const [checked, setChecked] = useState<Record<number, boolean>>({}); // 품목 id → 골랐는지
  const [expandedId, setExpandedId] = useState<number | null>(productId); // 대시보드에서 온 품목은 근거를 펼쳐 둔다
  const [qty, setQty] = useState<Record<number, { value: string; units: number | null }>>({}); // 입수가 바뀌면 이전 수량을 재사용하지 않는다
  const [busy, setBusy] = useState(false); // 만드는 중이면 버튼 잠금·글자 변경
  const sending = useRef(false); // 상태값은 다음 화면 갱신 뒤에야 바뀌어 더블클릭을 못 막으므로 즉시 바뀌는 ref 로 한 번 더 막는다
  const [result, setResult] = useState<Created[]>([]); // 마지막으로 성공한 초안들
  const [error, setError] = useState<unknown>(null); // 초안 만들기 오류

  const load = useCallback(async () => {
    setLoadError(null); // 다시 시도하면 오류 문장을 지운다
    try {
      const [rec, draftList] = await Promise.all([
        api<{ items: Item[]; excluded: Excluded[] }>("/recommendations"), // 추천은 요청할 때 서버가 계산한다
        // shortcut: 작성 중 발주서 100장까지만 본다(업체당 DRAFT 1장이라 업체 100곳까지). 넘으면 API 에 칸을 붙인다
        apiList<PurchaseOrder>("/purchase-orders?status=DRAFT&page_size=100"),
      ]);
      const map: Record<number, Draft> = {}; // 품목 id → 작성 중 발주서
      for (const o of draftList.data) { // 조회한 초안에서 품목별로 표시할 값을 찾는다
        for (const i of o.items) map[i.product_id] = {
          id: o.id, po_number: o.po_number, quantity: i.quantity, box_quantity: i.box_quantity, unit: i.unit,
        }; // 저장된 수량과 단위를 그대로 쓴다
      }
      setItems(productId === null ? rec.items : rec.items.filter((i) => i.product_id === productId));
      setExcluded(productId === null ? rec.excluded : rec.excluded.filter((i) => i.product_id === productId));
      setDrafts(map); // 체크·수량 입력은 그대로 둔다
    } catch (e) {
      setLoadError(e); // 화면에 "다시 시도" 버튼과 함께 보인다
    }
  }, [productId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 화면이 열릴 때 목록을 불러와 상태에 넣는 것이 이 효과의 목적이다
    load();
  }, [load]);

  // 보낼 줄: 고른 품목 중 지금 목록에 있고 작성 중 초안에 없는 것 (초안에 있는 줄은 체크를 막아 두었다)
  const selected = (items ?? []).filter((i) => checked[i.product_id] && !drafts[i.product_id]);
  const supplierCount = new Set(selected.map((i) => i.supplier_id)).size; // 같은 업체의 품목은 여러 개 골라도 업체 한 곳으로 센다
  const linkedDrafts = new Set<number>(); // 초안 상세 링크를 표에 먼저 배치하고 안내에서는 중복을 피한다
  const editOf = (i: Item) => {
    const edit = qty[i.product_id];
    return edit && edit.units === i.units_per_box ? edit.value : undefined;
  };
  const quantityOf = (i: Item) => editOf(i) ?? String(i.recommended_box_quantity ?? i.recommended_quantity);
  const maxFor = (i: Item) => i.units_per_box != null ? boxLimit(i.units_per_box) : MAX_ORDER_QUANTITY;

  async function createDrafts() {
    if (sending.current) return; // 이미 만드는 중이면 두 번째 클릭은 버린다
    const invalid = selected.find((i) => {
      const count = Number(quantityOf(i));
      return !Number.isInteger(count) || count < 1 || count > maxFor(i);
    });
    if (invalid) {
      setResult([]);
      setError(`${invalid.product_sku} 발주 수량은 1~${maxFor(invalid).toLocaleString("ko-KR")}${invalid.units_per_box != null ? "박스" : " (재고 단위)"}로 입력하세요.`);
      return;
    }
    sending.current = true; // 즉시 잠금
    setBusy(true); // 버튼 잠금·"만드는 중…"
    const body = {
      items: selected.map((i) => {
        const product_id = i.product_id;
        if (i.units_per_box == null) return { product_id, quantity: Number(quantityOf(i)) };
        const edit = editOf(i); // 박스 수를 고치지 않았으면 서버가 최신 추천으로 다시 올림한다
        return edit === undefined ? { product_id } : { product_id, box_quantity: Number(edit) };
      }),
    };
    try {
      const orders = await api<Created[]>("/recommendations/drafts", { method: "POST", body });
      setError(null);
      setResult(orders); // 만든(또는 추가한) 발주서 링크를 보여 준다
      await load(); // 방금 넣은 품목이 "초안 작성 중" 으로 바뀌게 다시 불러온다
    } catch (e) {
      setResult([]);
      setError(e); // 입력값(체크·수량)은 지우지 않는다
    } finally {
      sending.current = false; // 성공·실패 모두 다시 누를 수 있게 푼다
      setBusy(false);
    }
  }

  if (loadError) return (
    <section>
      <h1>발주 추천</h1>
      <ErrorText error={loadError} />
      <button type="button" onClick={load}>다시 시도</button>
    </section>
  ); // 추천 조회 실패
  if (!items) return <section><h1>발주 추천</h1><p>불러오는 중…</p></section>; // 불러오기 전

  const allInDraft = items.length > 0 && items.every((i) => drafts[i.product_id]); // 작업 가능한 품목이 하나도 없는지 확인한다

  return (
    <section>
      <h1>발주 추천</h1>
      <p style={S.hint}>최근 30일 판매를 기준으로 지금 발주가 필요한 품목입니다. 고른 품목은 공급업체별 발주서 초안(작성 중)으로 만들어지고, 승인은 발주 화면에서 합니다.</p>
      {productId !== null && <p><Link href="/recommendations">전체 발주 추천 보기</Link></p>}

      {/* 선택 요약과 작업 버튼은 표의 가로 스크롤 밖에 둔다 */}
      {items.length > 0 && (
        <form style={{ ...S.toolbar, alignItems: "center" }} onSubmit={(e) => { e.preventDefault(); void createDrafts(); }}>
          {/* 모든 추천 품목에 초안이 있으면 버튼이 잠긴 이유를 안내한다 */}
          {allInDraft ? <span role="status" style={S.hint}>추천 품목이 모두 초안에 들어 있습니다.</span>
            : <span role="status" style={S.num}>{selected.length}품목 선택 · 공급업체 {supplierCount}곳</span>}
          {/* 기존 제출 제한과 처리 중 잠금을 유지한다 */}
          <button type="submit" disabled={busy || selected.length === 0 || selected.length > MAX_ITEMS}>
            {busy ? "만드는 중…" : "발주서 초안 만들기"}
          </button>
          {selected.length > MAX_ITEMS && <span style={S.error}>한 번에 {MAX_ITEMS}개까지 만들 수 있습니다. 선택을 줄여 주세요.</span>}
        </form>
      )}

      {items.length === 0 ? <p style={S.empty}>{productId === null ? "지금 발주가 필요한 품목이 없습니다." : "선택한 품목은 현재 발주 추천 대상이 아닙니다."}</p> : (
        <div style={S.tableBox}>
          {/* 좁은 화면에서는 이 상자 안에서만 가로로 스크롤한다 */}
          <table style={S.table}>
            <thead>
              <tr style={S.headRow}>
                <th scope="col">선택</th>{/* 초안에 넣을 품목 선택 */}
                <th scope="col" style={S.midCol}>품목</th>{/* 품목명과 근거 요약 */}
                <th scope="col" style={S.midCol}>공급업체</th>{/* 공급업체명과 리드타임 */}
                <th scope="col">상태</th>{/* 품절 위험과 발주 필요 */}
                <th scope="col" className={styles.numericColumn} style={S.num}>가용재고</th>{/* 숫자 머리 칸도 오른쪽 정렬 */}
                <th scope="col" className={styles.numericColumn} style={S.num}>재주문점</th>{/* 가용재고와 비교할 기준 */}
                <th scope="col" className={styles.numericColumn} style={S.num}>발주 수량</th>{/* 서버 추천 수량과 입력값 */}
              </tr>
            </thead>
            <tbody>
              {items.map((i) => {
                const draft = drafts[i.product_id]; // 작성 중인 초안에 이미 들어 있는 품목인지 확인한다
                const linkDraft = draft && !linkedDrafts.has(draft.id); // 같은 초안은 처음 보이는 곳에서만 연결한다
                if (linkDraft) linkedDrafts.add(draft.id); // 같은 초안의 다음 품목에서는 번호만 표시한다
                const cover = i.current_stock / i.avg_daily_sales; // 기존 표시용 커버 일수 계산 (판매가 있는 품목만 추천된다)
                const picked = !draft && !!checked[i.product_id]; // 초안에 이미 든 품목은 선택할 수 없다
                const cell = picked ? S.selectedRow : undefined; // 선택한 품목은 본문과 펼친 근거의 배경을 강조한다
                const open = expandedId === i.product_id; // 이 품목의 근거가 펼쳐졌는지 확인한다
                const evidenceId = "recommendation-evidence-" + i.product_id; // 버튼과 펼쳐진 근거를 연결한다
                const boxCount = Number(quantityOf(i)); // 보조 문구에는 입력한 박스를 재고 단위로 환산한다
                return (
                  <Fragment key={i.product_id}>
                    <tr style={S.row}>
                      <td style={picked ? { ...S.selectedRow, ...S.selectedMark } : undefined}>
                        {/* 선택한 줄의 첫 칸에는 기존 파란 세로줄을 표시한다 */}
                        {draft ? (
                          <span className={styles.locked}>{/* 초안에 든 품목은 잠금 그림과 글자로 표시한다 */}
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                              <rect x="5" y="10" width="14" height="11" rx="2" />{/* 잠금 몸체 */}
                              <path d="M8 10V7a4 4 0 1 1 8 0v3" />{/* 잠금 고리 */}
                            </svg>
                            선택 불가
                          </span>
                        ) : (
                          <label className={styles.pickTarget}>{/* 체크박스 주변을 눌러도 이 품목을 선택한다 */}
                            <input type="checkbox" aria-label={i.product_sku + " 선택"} checked={picked}
                              onChange={(e) => setChecked({ ...checked, [i.product_id]: e.target.checked })} />
                          </label>
                        )}
                      </td>
                      <td style={cell}>
                        {i.product_name}<span style={S.sub}>{i.product_sku}</span>
                        {/* 접힌 상태에서도 서버가 준 두 숫자로 짧은 판단 근거를 보여 준다 */}
                        <button type="button" className={styles.evidenceToggle} aria-expanded={open} aria-controls={evidenceId}
                          onClick={() => setExpandedId(open ? null : i.product_id)}>{/* 다른 품목을 열면 이전 근거는 닫힌다 */}
                          <span>현재 {quantityLabel(i.current_stock, i.unit)} · 하루 {fmt(i.avg_daily_sales)}{i.unit} 판매 · 입고까지 {i.lead_time_days}일</span>
                          <span className={styles.evidenceAction}>{open ? "접기" : "자세히"}</span>
                        </button>
                      </td>
                      <td style={cell}>{i.supplier_name}<span style={S.sub}>리드타임 {i.lead_time_days}일</span></td>
                      <td style={{ ...S.nowrap, ...cell }}>
                        {/* 기존 표시 기준을 유지한다. 커버 일수가 리드타임 이하면 품절 위험이다 */}
                        {cover <= i.lead_time_days ? <StatusBadge kind="danger">품절 위험</StatusBadge> : <StatusBadge kind="info">발주 필요</StatusBadge>}
                        {draft && <span style={S.sub}>초안 작성 중 ({linkDraft ? <Link href={"/purchase-orders/" + draft.id}>{draft.po_number}</Link> : draft.po_number})</span>}
                      </td>
                      <td className={styles.numericColumn} style={{ ...S.num, ...S.key, ...cell }}>{quantityLabel(i.available, i.unit)}</td>{/* 서버의 가용재고 */}
                      <td className={styles.numericColumn} style={{ ...S.num, ...S.key, ...cell }}>{fmt(i.reorder_point)}{i.unit}</td>{/* 서버의 재주문점 */}
                      <td className={styles.numericColumn} style={{ ...S.num, ...cell }}>
                        {draft ? (
                          <>{/* 편집 칸 없이 서버에 저장된 초안 수량을 보여 준다 */}
                            <span className={styles.draftQuantity}>{/* 상태와 저장된 수량을 한 줄에서 읽는다 */}
                              <StatusBadge kind="unknown" icon="draft">초안</StatusBadge>{/* 연필 아이콘으로 작성 중인 수량임을 나타낸다 */}
                              <strong>{draft.box_quantity != null ? quantityLabel(draft.box_quantity, "박스") : draft.quantity}</strong>
                            </span>
                            {draft.box_quantity != null && <span style={S.sub}>재고 {quantityLabel(draft.quantity, draft.unit)}</span>}
                            {draft.quantity !== i.recommended_quantity && <span style={S.sub}>추천 <strong>{quantityLabel(i.recommended_quantity, i.unit)}</strong></span>}
                          </>
                        ) : (
                          <>{/* 선택 가능한 품목만 수량을 고칠 수 있고 추천 수량은 서버 값이다 */}
                            <input type="number" min={1} max={maxFor(i)} step={1}
                              aria-label={i.product_sku + (i.units_per_box != null ? " 발주 박스 수" : " 발주 수량")}
                              style={S.numInput} value={quantityOf(i)}
                              onChange={(e) => setQty({ ...qty, [i.product_id]: { value: e.target.value, units: i.units_per_box } })} />
                            {i.units_per_box != null && <span style={S.sub}>
                              {boxCount > 0 ? `${quantityLabel(boxCount, "박스")} · ${quantityLabel(boxCount * i.units_per_box, i.unit)}` : `1박스 · ${quantityLabel(i.units_per_box, i.unit)}`}
                            </span>}
                            <span style={S.sub}>{i.units_per_box != null ? "필요 수량" : "추천"} {quantityLabel(i.recommended_quantity, i.unit)}</span>
                          </>
                        )}
                      </td>
                    </tr>
                    {/* 펼친 품목 아래에만 구분되는 바탕의 근거 상자를 표시한다 */}
                    <tr id={evidenceId} hidden={!open}>
                      <td colSpan={7} style={cell}>
                        <div className={styles.evidencePanel}>
                          <h3 className={styles.evidenceTitle}>추천 근거 · {i.product_name}</h3>{/* 어떤 품목의 근거인지 제목으로 표시한다 */}
                          <dl className={styles.evidenceFacts}>
                            <div><dt>현재고</dt><dd style={S.num}>{i.current_stock}</dd></div>{/* 서버의 현재고 */}
                            <div><dt>발주 진행 중</dt><dd style={S.num}>{i.in_transit}</dd></div>{/* 서버의 미입고 발주 수량 */}
                            <div><dt>일평균 판매</dt><dd style={S.num}>{fmt(i.avg_daily_sales)}</dd></div>{/* 서버의 일평균을 표시용으로 반올림한다 */}
                            <div><dt>재고 커버 일수</dt><dd style={S.num}>{fmt(cover)}일</dd></div>{/* 기존 화면의 커버 일수 */}
                          </dl>
                          <p className={styles.evidenceReason}>가용 {quantityLabel(i.available, i.unit)} ≤ 재주문점 {fmt(i.reorder_point)}{i.unit}</p>
                          <p className={styles.evidenceReason}>{i.reason}</p>{/* 서버의 전체 이유를 그대로 보여 준다 */}
                        </div>
                      </td>
                    </tr>
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {result.length > 0 && (
        <div role="status" style={S.ok}>
          {result.map((o) => (
            <p key={o.id}>
              {/* 표에 초안 행이 없을 때만 성공 안내에서 상세 링크를 제공한다 */}
              {linkedDrafts.has(o.id) ? o.po_number : <Link href={"/purchase-orders/" + o.id}>{o.po_number}</Link>} ({o.supplier_name}){" "}
              {o.created ? "발주서 초안을 새로 만들었습니다." : "기존 초안에 추가했습니다."}
            </p>
          ))}
        </div>
      )}
      <DraftError error={error} linkedDrafts={linkedDrafts} onReload={() => { setError(null); load(); }} />
      {/* 새로고침하면 지난 오류 문장은 지운다 (체크·수량은 그대로) */}

      {(productId === null || excluded.length > 0) && <h2 style={S.sectionTitle}>추천에서 제외된 품목</h2>}
      {excluded.length === 0 ? (productId === null && <p style={S.empty}>제외된 품목이 없습니다.</p>) : (
        <div style={S.tableBox}>
        <table style={S.table}>
          <thead><tr style={S.headRow}><th>품목</th><th>상태</th><th>제외 사유</th></tr></thead>
          <tbody>
            {excluded.map((e) => (
              <tr key={e.product_id} style={S.row}>
                <td>{e.product_name}<span style={S.sub}>{e.product_sku}</span></td>
                <td style={S.nowrap}><StatusBadge kind="unknown">판단 불가</StatusBadge></td>
                <td>{e.message}</td>{/* 제외 사유는 서버 문장을 그대로 보여 준다 */}
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </section>
  );
}

// 초안 만들기 오류 표시: 코드별로 안내를 덧붙이고, 그 밖은 서버 문장 그대로
function DraftError({ error, linkedDrafts, onReload }: { error: unknown; linkedDrafts: ReadonlySet<number>; onReload: () => void }) {
  if (typeof error === "string") return <p role="alert" style={S.error}>{error}</p>; // 화면에서 검증한 입력 오류
  if (!(error instanceof ApiError)) return <ErrorText error={error} />; // 오류 없음(null) 또는 알 수 없는 오류
  if (error.code === "NOT_RECOMMENDED" && Array.isArray(error.details)) return (
    <div role="alert" style={S.error}>
      <p>지금은 추천 대상이 아닌 품목이 있습니다. 추천 목록을 새로고침하세요.</p>
      <ul>
        {(error.details as { sku: string; reason: string }[]).map((d) => <li key={d.sku}>{d.sku}: {REASON_TEXT[d.reason] ?? d.reason}</li>)}
      </ul>
      <button type="button" onClick={onReload}>추천 목록 새로고침</button>
    </div>
  ); // 목록을 본 뒤 입고 등으로 재고가 바뀐 경우
  const order = error.details as { purchase_order_id?: number; po_number?: string } | null; // DUPLICATE_ITEM 이면 기존 초안 정보
  if (error.code === "DUPLICATE_ITEM" && order?.purchase_order_id) return (
    <p role="alert" style={S.error}>
      {error.message} {!linkedDrafts.has(order.purchase_order_id) && <Link href={"/purchase-orders/" + order.purchase_order_id}>{order.po_number} 열기</Link>}{/* 표에 이미 같은 링크가 있으면 안내만 표시한다 */}
    </p>
  ); // 이미 초안에 든 품목 (같은 요청을 두 번 보낸 경우 포함)
  return <ErrorText error={error} labels={PO_LABELS} />; // INACTIVE_REFERENCE·422 등: 서버 문장 그대로
}
