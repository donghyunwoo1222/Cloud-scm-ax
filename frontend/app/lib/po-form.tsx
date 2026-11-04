"use client"; // 입력을 다루는 폼이라 브라우저에서 실행

import Link from "next/link"; // 기존 발주서로 가는 링크
import { useRouter } from "next/navigation"; // 저장 후 상세 화면으로 이동
import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, ApiError, apiList } from "./api"; // 공통 API 호출 함수, 서버 오류
import { ErrorText } from "./list"; // 서버 오류 표시
import { PO_LABELS, PurchaseOrder } from "./po"; // 발주서 모양·칸 이름
import { S } from "./styles"; // 화면 공통 스타일

type Option = { id: number; name: string }; // 공급업체 선택지
type ProductOption = { id: number; sku: string; name: string; unit_cost: number }; // 품목 선택지
type Line = { product_id: string; quantity: string; unit_price: string }; // 품목 줄 입력값 (모두 글자로 다루고 보낼 때 숫자로)

const EMPTY_LINE: Line = { product_id: "", quantity: "", unit_price: "" }; // 빈 줄
const num = (v: string) => (v === "" ? null : Number(v)); // "10" → 10, 비우면 null (서버가 422 로 막는다. 1 이상·0 이상 검사는 서버가 한다)

// 발주서 작성·수정 폼 하나. order 가 있으면 수정(DRAFT 의 items 전체 교체), 없으면 새 작성
export function PoForm({ order }: { order?: PurchaseOrder }) {
  const router = useRouter(); // 저장 후 이동
  const [suppliers, setSuppliers] = useState<Option[]>([]); // 활성 공급업체 (작성할 때만 고른다)
  const [products, setProducts] = useState<ProductOption[]>([]); // 활성 품목
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체
  const [dueDate, setDueDate] = useState(order?.due_date ?? ""); // 약속 납기
  const [memo, setMemo] = useState(order?.memo ?? ""); // 메모
  const [lines, setLines] = useState<Line[]>(
    order ? order.items.map((i) => ({ product_id: String(i.product_id), quantity: String(i.quantity), unit_price: String(i.unit_price) })) : [{ ...EMPTY_LINE }],
  ); // 품목 줄들 (수정이면 지금 줄들로 시작)
  const [error, setError] = useState<unknown>(null); // 저장 오류 (입력값은 지우지 않는다)

  useEffect(() => {
    // shortcut: 활성 100개까지만 불러온다(서버 page_size 최대). 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<ProductOption>("/products?page_size=100").then((r) => setProducts(r.data)).catch(setError);
    if (!order) apiList<Option>("/suppliers?page_size=100").then((r) => setSuppliers(r.data)).catch(setError);
  }, [order]);

  // 선택 상자의 품목: 활성 품목 + (수정일 때) 이미 든 품목이 지금 비활성이어도 이름이 보이게 함께 넣는다
  const options = [
    ...products,
    ...(order?.items ?? []).filter((i) => !products.some((p) => p.id === i.product_id)).map((i) => ({ id: i.product_id, sku: i.product_sku, name: i.product_name, unit_cost: i.unit_price })),
  ];

  function setLine(index: number, patch: Partial<Line>) {
    setLines((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row))); // 그 줄만 바꾼다
  }

  // 품목을 고르거나 바꾸면 단가 칸을 그 품목의 단가로 채운다 (단가를 직접 고치고 싶으면 품목을 고른 뒤에 고친다)
  function pickProduct(index: number, productId: string) {
    const cost = options.find((p) => String(p.id) === productId)?.unit_cost; // 고른 품목의 단가
    setLine(index, { product_id: productId, unit_price: cost === undefined ? "" : String(cost) }); // 선택을 비우면 단가도 비운다
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    const items = lines.map((l) => ({ product_id: num(l.product_id), quantity: num(l.quantity), unit_price: num(l.unit_price) })); // 숫자로 바꿔 보낸다
    try {
      const saved = order
        ? await api<PurchaseOrder>(`/purchase-orders/${order.id}`, { method: "PATCH", body: { due_date: dueDate || null, memo: memo || null, items } }) // 수정: items 전체 교체
        : await api<PurchaseOrder>("/purchase-orders", { method: "POST", body: { supplier_id: num(supplierId), due_date: dueDate || null, memo: memo || null, items } }); // 작성
      router.push(`/purchase-orders/${saved.id}`); // 저장되면 상세 화면으로
    } catch (e) {
      setError(e); // 서버 문장 그대로 보여주고 입력값은 그대로 둔다
    }
  }

  // 이미 DRAFT 가 있는 공급업체면 서버가 details 에 기존 발주서 번호를 준다
  const duplicate = error instanceof ApiError && error.code === "DUPLICATE_DRAFT" ? (error.details as { purchase_order_id: number; po_number: string }) : null;

  return (
    <form onSubmit={submit}>
      <div style={S.formGrid}>
        {order ? (
          <p>공급업체: {order.supplier_name} (바꿀 수 없습니다. 다른 업체는 새 발주서로 작성하세요)</p>
        ) : (
          <label>공급업체*
            <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} style={S.block}>
              <option value="">선택</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
        )}
        <label>약속 납기 <input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></label>
        <label>메모 <input value={memo} onChange={(e) => setMemo(e.target.value)} /></label>
      </div>

      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>품목*</th><th>수량*</th><th>단가(원)*</th><th></th></tr>
        </thead>
        <tbody>
          {lines.map((line, index) => (
            <tr key={index}>
              <td>
                <select value={line.product_id} onChange={(e) => pickProduct(index, e.target.value)} aria-label="품목">
                  <option value="">선택</option>
                  {options.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
                </select>
              </td>
              <td><input type="number" value={line.quantity} onChange={(e) => setLine(index, { quantity: e.target.value })} aria-label="수량" /></td>
              <td><input type="number" value={line.unit_price} onChange={(e) => setLine(index, { unit_price: e.target.value })} aria-label="단가" /></td>
              <td><button type="button" onClick={() => setLines((rows) => rows.filter((_, i) => i !== index))}>줄 삭제</button></td>
              {/* 0줄이 되면 서버가 422 (품목 줄 1개 이상)로 막는다 */}
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => setLines((rows) => [...rows, { ...EMPTY_LINE }])}>줄 추가</button>

      <p style={S.buttons}>
        <button type="submit">{order ? "수정 저장" : "작성"}</button>
        <Link href={order ? `/purchase-orders/${order.id}` : "/purchase-orders"}>취소</Link>
      </p>
      <ErrorText error={error} labels={PO_LABELS} />
      {duplicate && <p><Link href={`/purchase-orders/${duplicate.purchase_order_id}`}>기존 발주서 {duplicate.po_number} 열기</Link></p>}
      {/* DUPLICATE_DRAFT: 문장은 위 ErrorText 가 보여주고, 여기서 기존 초안으로 가는 링크를 준다 */}
    </form>
  );
}
