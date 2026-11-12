"use client"; // 입력을 다루는 폼이라 브라우저에서 실행

import Link from "next/link"; // 발주 입고 이력에서 발주서로 이동한다.
import { FormEvent, useCallback, useEffect, useId, useRef, useState } from "react"; // 폼 제출, 불러오기, 현재고 안내 연결, 중복 방지, 상태

import { api, apiList } from "./api"; // 공통 API 호출 함수
import { Field } from "./field"; // 모바일에서 라벨이 테두리에 걸치는 입력 항목
import { ErrorText } from "./list"; // 서버 오류 표시
import { movementOptions, skuWithOptions } from "./options"; // 품목 옵션 요약
import { ShipmentTypeBadge, StatusBadge } from "./status-badge"; // 출고 유형과 발주 입고 배지
import { ProductOption, ProductPicker } from "./product-picker"; // 전체 품목에서 검색해 바로 선택한다
import { quantityLabel } from "./po"; // 품목 단위로 재고·수량을 표시한다.
import { S } from "./styles"; // 화면 공통 스타일

export type MovementType = "RECEIPT" | "SALE" | "DISPOSAL" | "OTHER_OUT" | "ADJUSTMENT"; // 서버가 받는 유형 5개
export const TYPE_LABEL: Record<string, string> = {
  RECEIPT: "입고", SALE: "판매", DISPOSAL: "폐기", OTHER_OUT: "기타 출고", ADJUSTMENT: "실사 조정", CORRECTION: "정정",
}; // 유형 → 화면 이름 (CORRECTION 은 등록 폼에는 없고 이력 목록에서만 보인다)
const CHANNELS = [["SMARTSTORE", "스마트스토어"], ["OWN_MALL", "자사몰"], ["OTHER", "기타"]]; // 판매 채널 선택지
export const CHANNEL_LABEL: Record<string, string> = Object.fromEntries(CHANNELS); // 채널 코드 → 화면 이름 (이력 목록용)
const LABELS = { product_id: "품목", quantity: "수량", direction: "방향", reason: "사유", sales_channel: "판매 채널", movement_date: "일자", memo: "메모" }; // 오류 details 칸 이름 → 화면 이름 (movement_date 는 폼 안에서 "입고일"/"출고일"로 덮어쓴다)

// 서울 기준 오늘 (YYYY-MM-DD). 서버도 서울 기준이라 브라우저 시간대와 상관없이 맞춘다
export const seoulToday = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });

// 입출고 등록 폼. types 로 이 화면에서 고를 수 있는 유형을 정한다 (입고 화면은 입고만, 출고 화면은 나머지)
export function MovementForm({ types, initialType = types[0] }: { types: MovementType[]; initialType?: MovementType }) {
  const [type, setType] = useState<MovementType>(initialType); // 직접 열었으면 실사 조정도 기본으로 고를 수 있다.
  const dateLabel = type === "ADJUSTMENT" ? "조정일" : type === "RECEIPT" ? "입고일" : "출고일";
  const labels = { ...LABELS, movement_date: dateLabel }; // 오류 문장의 칸 이름도 같은 글자로
  const [product, setProduct] = useState<ProductOption>(); // 검색 결과가 바뀌어도 고른 품목은 유지한다.
  const productId = product?.id; // 현재고 조회와 등록에 쓸 품목 번호
  const [quantity, setQuantity] = useState(""); // 수량 (글자로 다루고 보낼 때 숫자로)
  const [channel, setChannel] = useState("OWN_MALL"); // 판매 채널 (판매일 때만 보낸다)
  const [direction, setDirection] = useState("OUT"); // 조정 방향 (조정일 때만 보낸다)
  const [reason, setReason] = useState(""); // 조정 사유
  const [today, setToday] = useState(""); // 서울 기준 오늘 (서버 렌더링 때 시각을 읽으면 빌드가 막혀 화면이 열린 뒤 채운다)
  const [date, setDate] = useState(""); // 입출고일, 기본 서울 오늘
  const [memo, setMemo] = useState(""); // 메모
  const [stock, setStock] = useState<number | "loading" | "unavailable">("loading"); // 0도 조회된 현재고로 표시한다
  const stockStatusId = useId();
  const stockRequest = useRef(0); // 품목 변경이나 저장보다 먼저 시작한 조회는 버린다
  const [done, setDone] = useState(""); // 성공 안내 문장
  const [error, setError] = useState<unknown>(null); // 등록 오류
  const [busy, setBusy] = useState(false); // 등록 중이면 버튼을 잠그고 글자를 바꾼다
  const sending = useRef(false); // 상태값은 다음 화면 갱신 뒤에야 바뀌어 더블클릭을 못 막으므로, 즉시 바뀌는 ref 로 한 번 더 막는다
  const [savedCount, setSavedCount] = useState(0); // 등록에 성공한 횟수 (바뀌면 아래 최근 이력을 다시 불러온다)

  useEffect(() => {
    const t = seoulToday(); // 화면이 열린 뒤 오늘 날짜를 정한다
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 브라우저에서만 알 수 있는 오늘 날짜를 상태에 넣는 것이 이 효과의 목적이다
    setToday(t); setDate(t); // 날짜 상한과 기본값
  }, []);

  useEffect(() => {
    if (!done) return; // 안내가 없으면 할 일 없음
    const timer = setTimeout(() => setDone(""), 8000); // 약 8초 뒤 성공 안내를 지운다
    return () => clearTimeout(timer); // 그 전에 안내가 바뀌거나 화면을 떠나면 이전 타이머는 취소
  }, [done]);

  useEffect(() => {
    if (!productId) return; // 품목을 안 골랐으면 조회하지 않는다 (표시도 아래에서 숨긴다)
    const request = ++stockRequest.current;
    api<{ current_stock: number }>(`/stock/${productId}`)
      .then((s) => { if (request === stockRequest.current) setStock(s.current_stock); })
      .catch(() => { if (request === stockRequest.current) setStock("unavailable"); });
    return () => { stockRequest.current += 1; };
  }, [productId]);

  async function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    if (sending.current) return; // 이미 등록 중이면 두 번째 제출은 버린다
    sending.current = true; // 즉시 잠금
    setBusy(true); // 버튼 잠금·글자 변경
    setDone(""); // 다음 등록을 누르면 이전 성공 안내는 지운다
    const label = `${product?.sku ?? ""} ${TYPE_LABEL[type]} ${quantityLabel(Number(quantity), product?.unit)}`; // 예: "KB-101 입고 5개" (유형·수량도 등록 직전 값)
    const body: Record<string, unknown> = {
      product_id: productId ?? null, // 비우면 null → 서버가 422
      movement_type: type,
      quantity: quantity === "" ? null : Number(quantity), // 1 이상 정수 검사는 서버가 한다
      movement_date: date || null, // 비우면 서버가 오늘로
      memo: memo || null,
    };
    if (type === "SALE") body.sales_channel = channel; // 채널은 판매일 때만
    if (type === "ADJUSTMENT") { body.direction = direction; body.reason = reason; } // 조정은 방향·사유 필수
    try {
      const r = await api<{ stock_after: number }>("/inventory-movements", { method: "POST", body });
      setError(null);
      setDone(`${label}를 등록했습니다 · 현재고 ${quantityLabel(r.stock_after, product?.unit)}`); // 예: "KB-101 입고 5개를 등록했습니다 · 현재고 27개" (현재고는 서버가 돌려준 등록 직후 값)
      stockRequest.current += 1; // 등록 전에 요청한 재고가 새 수량을 덮지 않도록 한다
      setStock(r.stock_after);
      setQuantity(""); setReason(""); setMemo(""); // 다음 입력을 위해 비운다 (품목·유형·날짜는 유지)
      setSavedCount((n) => n + 1); // 방금 등록한 줄이 최근 이력 맨 위에 보이도록 다시 불러오게 한다
    } catch (e) {
      setDone("");
      setError(e); // 입력값은 지우지 않는다. 서버 문장 그대로 (재고 부족이면 현재고 숫자 포함)
    } finally {
      sending.current = false; // 성공·실패 모두 다시 누를 수 있게 푼다
      setBusy(false);
    }
  }

  return (
    <>
    <form className="form-compact field-form" onSubmit={submit} style={S.formGridWide}>
      <div className="movement-product field-product" style={{ flex: "1 1 220px", maxWidth: 320, minWidth: 0 }}>
        <div className="movement-product-label">
          <span className="field-label">품목*</span>
          <span id={stockStatusId} role="status">
            {product && (
              <span className="movement-stock">
                현재고 <strong>{stock === "loading" ? "확인 중…" : stock === "unavailable" ? "조회 실패" : quantityLabel(stock, product.unit)}</strong>
              </span>
            )}
          </span>
        </div>
        <ProductPicker label="품목" value={product} includeInactive disabled={busy} onSelect={(picked) => {
          if (picked.id !== productId) {
            stockRequest.current += 1;
            setStock("loading");
          }
          setProduct(picked);
          setDone("");
        }} />
      </div>
      {types.length > 1 && (
        <Field label="유형*" className={type === "SALE" ? "field-half" : ""}><select value={type} onChange={(e) => setType(e.target.value as MovementType)} style={S.block}>
            {types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select></Field>
      )}
      {type === "SALE" && (
        <Field label="판매 채널*" className="field-half"><select value={channel} onChange={(e) => setChannel(e.target.value)} style={S.block}>
            {CHANNELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></Field>
      )}
      {type === "ADJUSTMENT" && (
        <Field label="방향*"><select value={direction} onChange={(e) => setDirection(e.target.value)} style={S.block}>
            <option value="OUT">감소 (실제가 더 적음)</option>
            <option value="IN">증가 (실제가 더 많음)</option>
          </select></Field>
      )}
      <Field label={`수량${product ? ` (재고 단위 ${product.unit})` : ""}*`} className="field-half"><input type="number" inputMode="numeric" min={1} step={1} value={quantity} aria-describedby={product ? stockStatusId : undefined} onChange={(e) => setQuantity(e.target.value)} /></Field>
      <Field label={dateLabel} className="field-half">
        <input type="date" max={today || undefined} value={date} onChange={(e) => setDate(e.target.value)} />
        {/* 오늘 이후는 고를 수 없다 (서버도 막는다) */}
      </Field>
      {type === "ADJUSTMENT" && <Field label="사유*"><input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="예: 실사 차이" /></Field>}
      <Field label="메모" className="field-grow"><input value={memo} onChange={(e) => setMemo(e.target.value)} /></Field>
      <button type="submit" disabled={busy}>{busy ? "등록 중…" : "등록"}</button>
      <div style={S.fullRow}>
        <ErrorText error={error} labels={labels} />
        {done && <p role="status" style={S.ok}>{done}</p>}
      </div>
    </form>
    <RecentMovements types={types} refreshKey={savedCount} />
    {/* 등록 폼 아래의 최근 이력 표. 이력을 못 불러와도 위의 등록 폼은 그대로 동작한다 */}
    </>
  );
}

// 최근 이력 한 줄: GET /inventory-movements 응답 중 이 표가 쓰는 칸
type Recent = {
  id: number; // 이력 번호 (표의 줄 구분용)
  product_id: number; // 품목 번호 (지금 재고를 찾는 데 쓴다)
  product_sku: string | null; product_name: string | null; // 품목 SKU·이름 (이력 조회가 채워 준다)
  product_color?: string | null; product_size?: string | null; product_spec?: string | null; // 품목 옵션
  movement_type: string; direction: "IN" | "OUT"; // 유형, 늘림·줄임
  quantity: number; movement_date: string; // 수량, 입출고일
  sales_channel: string | null; reason: string | null; memo: string | null; // 판매 채널, 조정 사유, 메모
  product_unit: string | null; // 이력에 붙일 품목 단위
  purchase_order_id: number | null; // 연결된 발주서 번호
  current_stock: number | null; // 최근 이력 품목의 현재고
  purchase_order_item_id: number | null; // 값이 있으면 발주 입고 (발주 화면에서 들어온 줄)
};

// 등록 폼 아래 "최근 10건" 표. refreshKey 가 바뀌면(등록에 성공하면) 다시 불러온다
function RecentMovements({ types, refreshKey }: { types: MovementType[]; refreshKey: number }) {
  const isReceipt = types.length === 1 && types[0] === "RECEIPT"; // 입고 화면이면 true, 출고 화면이면 false
  const typesKey = types.join(","); // 유형 묶음을 글자 하나로 만든다 (아래 함수의 의존성으로 쓰기 쉽게)
  const [rows, setRows] = useState<Recent[] | null>(null); // 불러온 줄 (불러오기 전에는 null)
  const [loadError, setLoadError] = useState<unknown>(null); // 이력 불러오기 오류 (등록 폼의 오류와 따로 둔다)
  const latest = useRef(0); // 가장 마지막으로 보낸 요청 번호 (늦게 도착한 이전 응답을 버리는 데 쓴다)

  const load = useCallback(async () => {
    const mine = ++latest.current; // 이 요청의 번호를 정한다
    const params = new URLSearchParams({ sort: "registered", page_size: "10", include_current_stock: "true" }); // 등록 순서 최신순, 10건
    typesKey.split(",").forEach((t) => params.append("movement_type", t)); // 유형을 하나씩 반복해 붙인다 (한 요청에 여러 유형)
    try {
      const r = await apiList<Recent>(`/inventory-movements?${params}`); // 이력에 나온 품목의 현재고를 함께 받는다.
      if (mine !== latest.current) return; // 더 새로운 요청이 있으면 이 응답은 버린다
      setRows(r.data); // 불러온 줄을 보여 준다
      setLoadError(null); // 이전 실패 안내를 지운다
    } catch (e) {
      if (mine === latest.current) setLoadError(e); // 실패하면 안내만 보여 주고, 등록 폼은 그대로 쓸 수 있다
    }
  }, [typesKey]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 이력을 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    load(); // 처음 열 때와 등록에 성공할 때마다 불러온다
  }, [load, refreshKey]);

  return (
    <section>
      <h2 style={S.sectionTitle}>{isReceipt ? "최근 입고 10건" : "최근 출고·조정 10건"}</h2>
      <p style={S.hint}>등록한 순서대로 보입니다. 입출고일을 과거로 등록해도 방금 등록한 줄이 맨 위에 옵니다.</p>
      {loadError !== null && (
        <div>
          <ErrorText error={loadError} />
          <button type="button" onClick={load}>다시 불러오기</button>
          {/* 실패해도 위의 등록 폼은 그대로 동작한다. 이 버튼으로 이력만 다시 불러온다 */}
        </div>
      )}
      {rows === null && loadError === null && <p style={S.hint}>불러오는 중…</p>}
      {rows !== null && rows.length === 0 && <p style={S.empty}>아직 등록한 이력이 없습니다.</p>}
      {rows !== null && rows.length > 0 && (
        <>
        <p style={S.hint}>현재고(지금) 열은 각 줄 등록 후 재고가 아니라 지금 재고입니다.</p>
        {/* 오해를 막는 설명을 표 바로 위에 늘 보이게 둔다 (마우스를 올려야 보이는 방식은 쓰지 않는다) */}
        <div className="table-view" style={S.tableBox}>
          {/* 730px 미만에서는 이 표를 숨기고 아래 압축 행 목록을 보여 준다 */}
          <table style={S.table}>
            <thead>
              <tr style={S.headRow}>
                <th>{isReceipt ? "입고일" : "출고·조정일"}</th><th>품목</th>
                {!isReceipt && <th>유형</th>}
                <th style={S.num}>수량</th><th style={S.num}>현재고(지금)</th><th>메모</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((m) => (
                <tr key={m.id} style={S.row}>
                  <td style={S.nowrap}>{m.movement_date}</td>
                  <td>{m.product_name}<span style={S.sub}>{skuWithOptions(m.product_sku, movementOptions(m))}</span></td>
                  {!isReceipt && (
                    <td style={S.nowrap}>
                      <ShipmentTypeBadge type={m.movement_type}>{TYPE_LABEL[m.movement_type] ?? m.movement_type}</ShipmentTypeBadge>
                      {m.sales_channel && <span style={S.sub}>{CHANNEL_LABEL[m.sales_channel] ?? m.sales_channel}</span>}
                      {/* 판매는 채널을 유형 아래에 작게 보인다 */}
                    </td>
                  )}
                  <td style={S.num}>{m.direction === "IN" ? "+" : "−"}{quantityLabel(m.quantity, m.product_unit ?? undefined)}</td>
                  {/* 늘면 +, 줄면 − (실사 조정은 방향이 둘 다 있다) */}
                  <td style={S.num}>{m.current_stock == null ? "-" : quantityLabel(m.current_stock, m.product_unit ?? undefined)}</td>
                  {/* 이 품목의 지금 재고 (재고 목록에 없거나 못 불러왔으면 "-") */}
                  <td>
                    {m.purchase_order_id != null ? <Link href={`/purchase-orders/${m.purchase_order_id}`}>발주 입고 보기</Link>
                      : m.purchase_order_item_id != null && <StatusBadge kind="info">발주 입고</StatusBadge>}
                    {/* 발주 화면에서 들어온 줄은 "발주 입고" 배지로 구분한다 */}
                    {m.purchase_order_item_id !== null && (m.reason || m.memo) && " "}
                    {[m.reason, m.memo].filter(Boolean).join(" · ")}
                    {/* 조정 사유와 메모를 함께 */}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="compact-list" aria-label={isReceipt ? "최근 입고" : "최근 출고·조정"}>
          {rows.map((m) => (
            <li key={m.id} className="compact-row">
              <div className="compact-main">
                <strong>{m.product_name}</strong>
                <span className="compact-value">{m.direction === "IN" ? "+" : "−"}{quantityLabel(m.quantity, m.product_unit ?? undefined)}</span>
                {/* 1줄: 품목과 수량 (늘면 +, 줄면 −) */}
              </div>
              <div className="compact-sub">
                <span>{skuWithOptions(m.product_sku, movementOptions(m))}</span>
                {!isReceipt && <span><ShipmentTypeBadge type={m.movement_type}>{TYPE_LABEL[m.movement_type] ?? m.movement_type}</ShipmentTypeBadge></span>}
                {m.sales_channel && <span>{CHANNEL_LABEL[m.sales_channel] ?? m.sales_channel}</span>}
                <span>{m.movement_date}</span>
                {/* 2줄: SKU · 유형 · 채널 · 날짜 (지금 재고는 표에서, 등록 직후 안내에도 나온다) */}
              </div>
              {(m.purchase_order_item_id != null || m.reason || m.memo) && (
                <div className="compact-note">
                  {m.purchase_order_id != null ? <Link href={`/purchase-orders/${m.purchase_order_id}`}>발주 입고 보기</Link>
                    : m.purchase_order_item_id != null && <StatusBadge kind="info">발주 입고</StatusBadge>}
                  {[m.reason, m.memo].filter(Boolean).join(" · ")}
                  {/* 발주 입고 링크와 조정 사유·메모는 있을 때만 3번째 줄로 */}
                </div>
              )}
            </li>
          ))}
        </ul>
        </>
      )}
    </section>
  );
}
