"use client"; // 입력을 다루는 폼이라 브라우저에서 실행

import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, apiList } from "./api"; // 공통 API 호출 함수
import { ErrorText } from "./list"; // 서버 오류 표시

export type MovementType = "RECEIPT" | "SALE" | "DISPOSAL" | "OTHER_OUT" | "ADJUSTMENT"; // 서버가 받는 유형 5개
export const TYPE_LABEL: Record<string, string> = {
  RECEIPT: "입고", SALE: "판매", DISPOSAL: "폐기", OTHER_OUT: "기타 출고", ADJUSTMENT: "실사 조정", CORRECTION: "정정",
}; // 유형 → 화면 이름 (CORRECTION 은 등록 폼에는 없고 이력 목록에서만 보인다)
const CHANNELS = [["SMARTSTORE", "스마트스토어"], ["OWN_MALL", "자사몰"], ["OTHER", "기타"]]; // 판매 채널 선택지
const LABELS = { product_id: "품목", quantity: "수량", direction: "방향", reason: "사유", sales_channel: "판매 채널", movement_date: "입출고일", memo: "메모" }; // 오류 details 칸 이름 → 화면 이름

// 서울 기준 오늘 (YYYY-MM-DD). 서버도 서울 기준이라 브라우저 시간대와 상관없이 맞춘다
export const seoulToday = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" });

type ProductOption = { id: number; sku: string; name: string }; // 선택 상자에 쓸 품목

// 입출고 등록 폼. types 로 이 화면에서 고를 수 있는 유형을 정한다 (입고 화면은 입고만, 출고 화면은 나머지)
export function MovementForm({ types }: { types: MovementType[] }) {
  const [products, setProducts] = useState<ProductOption[]>([]); // 활성 품목 선택지
  const [productId, setProductId] = useState(""); // 고른 품목
  const [type, setType] = useState<MovementType>(types[0]); // 고른 유형
  const [quantity, setQuantity] = useState(""); // 수량 (글자로 다루고 보낼 때 숫자로)
  const [channel, setChannel] = useState("OWN_MALL"); // 판매 채널 (판매일 때만 보낸다)
  const [direction, setDirection] = useState("OUT"); // 조정 방향 (조정일 때만 보낸다)
  const [reason, setReason] = useState(""); // 조정 사유
  const [today, setToday] = useState(""); // 서울 기준 오늘 (서버 렌더링 때 시각을 읽으면 빌드가 막혀 화면이 열린 뒤 채운다)
  const [date, setDate] = useState(""); // 입출고일, 기본 서울 오늘
  const [memo, setMemo] = useState(""); // 메모
  const [stock, setStock] = useState<number | null>(null); // 고른 품목의 현재고 (모르면 null)
  const [done, setDone] = useState(""); // 성공 안내 문장
  const [error, setError] = useState<unknown>(null); // 등록 오류

  useEffect(() => {
    const t = seoulToday(); // 화면이 열린 뒤 오늘 날짜를 정한다
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 브라우저에서만 알 수 있는 오늘 날짜를 상태에 넣는 것이 이 효과의 목적이다
    setToday(t); setDate(t); // 날짜 상한과 기본값
  }, []);

  useEffect(() => {
    // shortcut: 활성 품목 100개까지만 불러온다(서버 page_size 최대). 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<ProductOption>("/products?page_size=100").then((r) => setProducts(r.data)).catch(setError);
  }, []);

  useEffect(() => {
    if (!productId) return; // 품목을 안 골랐으면 조회하지 않는다 (표시도 아래에서 숨긴다)
    let alive = true; // 품목을 빨리 바꿀 때 늦게 온 이전 응답을 버리려는 표시
    api<{ current_stock: number }>(`/stock/${productId}`).then((s) => alive && setStock(s.current_stock)).catch(() => alive && setStock(null));
    return () => { alive = false; };
  }, [productId]);

  async function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    const body: Record<string, unknown> = {
      product_id: productId === "" ? null : Number(productId), // 비우면 null → 서버가 422
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
      setDone(`등록했습니다. 현재고는 ${r.stock_after}개입니다.`); // 서버가 돌려준 등록 직후 재고
      setStock(r.stock_after); // 품목 아래 현재고도 바로 갱신
      setQuantity(""); setReason(""); setMemo(""); // 다음 입력을 위해 비운다 (품목·유형·날짜는 유지)
    } catch (e) {
      setDone("");
      setError(e); // 입력값은 지우지 않는다. 서버 문장 그대로 (재고 부족이면 현재고 숫자 포함)
    }
  }

  return (
    <form onSubmit={submit} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.5rem", alignItems: "end", margin: "1rem 0" }}>
      <label>
        품목*
        <select value={productId} onChange={(e) => { setProductId(e.target.value); setStock(null); setDone(""); }} style={{ display: "block" }}>
          <option value="">선택하세요</option>
          {products.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
        </select>
        {productId && stock !== null && <small>현재고 {stock}개</small>}
        {/* 고른 품목의 현재고 */}
      </label>
      {types.length > 1 && (
        <label>
          유형*
          <select value={type} onChange={(e) => setType(e.target.value as MovementType)} style={{ display: "block" }}>
            {types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}
          </select>
        </label>
      )}
      {type === "SALE" && (
        <label>
          판매 채널*
          <select value={channel} onChange={(e) => setChannel(e.target.value)} style={{ display: "block" }}>
            {CHANNELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
      )}
      {type === "ADJUSTMENT" && (
        <label>
          방향*
          <select value={direction} onChange={(e) => setDirection(e.target.value)} style={{ display: "block" }}>
            <option value="OUT">감소 (실제가 더 적음)</option>
            <option value="IN">증가 (실제가 더 많음)</option>
          </select>
        </label>
      )}
      <label>수량* <input type="number" min={1} step={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} /></label>
      <label>
        입출고일
        <input type="date" max={today || undefined} value={date} onChange={(e) => setDate(e.target.value)} />
        {/* 오늘 이후는 고를 수 없다 (서버도 막는다) */}
      </label>
      {type === "ADJUSTMENT" && <label>사유* <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="예: 실사 차이" /></label>}
      <label>메모 <input value={memo} onChange={(e) => setMemo(e.target.value)} /></label>
      <button type="submit">등록</button>
      <div style={{ gridColumn: "1 / -1" }}>
        <ErrorText error={error} labels={LABELS} />
        {done && <p role="status" style={{ color: "green" }}>{done}</p>}
      </div>
    </form>
  );
}
