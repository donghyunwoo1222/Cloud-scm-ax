"use client"; // 입력을 다루는 폼이라 브라우저에서 실행

import Link from "next/link"; // 기존 발주서로 가는 링크
import { useRouter } from "next/navigation"; // 저장 후 상세 화면으로 이동
import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, ApiError, apiList } from "./api"; // 공통 API 호출 함수, 서버 오류
import { ErrorText } from "./list"; // 서버 오류 표시
import { boxLimit, MAX_ORDER_QUANTITY, PO_LABELS, PurchaseOrder, quantityLabel } from "./po"; // 발주서와 박스 환산 표시
import { ProductOption, ProductSearch, useProductOptions } from "./product-search"; // 발주 품목을 서버에서 검색한다.
import { S } from "./styles"; // 화면 공통 스타일

type Option = { id: number; name: string }; // 공급업체 선택지
type Line = { product_id: string; quantity: string; unit_price: string; box: boolean }; // 입력한 수량과 그 단위를 함께 기억한다

const EMPTY_LINE: Line = { product_id: "", quantity: "", unit_price: "", box: false }; // 빈 줄
const num = (v: string) => (v === "" ? null : Number(v)); // "10" → 10, 비우면 null (서버가 422 로 막는다. 1 이상·0 이상 검사는 서버가 한다)

// 발주서 작성·수정 폼 하나. order 가 있으면 수정(DRAFT 의 items 전체 교체), 없으면 새 작성
export function PoForm({ order }: { order?: PurchaseOrder }) {
  const router = useRouter(); // 저장 후 이동
  const [suppliers, setSuppliers] = useState<Option[]>([]); // 활성 공급업체 (작성할 때만 고른다)
  const productList = useProductOptions(); // 새 발주 품목은 활성만 조회한다.
  const [pickedProducts, setPickedProducts] = useState<Record<number, ProductOption>>({}); // 검색이 바뀌어도 고른 품목과 입수를 유지한다.
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체
  const [dueDate, setDueDate] = useState(order?.due_date ?? ""); // 약속 납기
  const [memo, setMemo] = useState(order?.memo ?? ""); // 메모
  const [lines, setLines] = useState<Line[]>(
    order ? order.items.map((i) => ({
      product_id: String(i.product_id), quantity: String(i.box_quantity ?? i.quantity),
      unit_price: String(i.unit_price), box: i.box_quantity != null,
    })) : [{ ...EMPTY_LINE }],
  ); // 품목 줄들 (수정이면 지금 줄들로 시작)
  const [error, setError] = useState<unknown>(null); // 저장 오류 (입력값은 지우지 않는다)

  useEffect(() => {
    if (!order) apiList<Option>("/suppliers?page_size=100").then((r) => setSuppliers(r.data)).catch(setError);
  }, [order]);

  // 선택 상자의 품목: 활성 품목 + (수정일 때) 이미 든 품목이 지금 비활성이어도 이름이 보이게 함께 넣는다
  const searchOptions = productList.isCurrent ? productList.rows : [];
  const options = new Map<number, ProductOption>((order?.items ?? []).map((i) => [i.product_id, {
    id: i.product_id, sku: i.product_sku, name: i.product_name, unit_cost: i.unit_price, unit: i.unit, is_active: false,
  }]));
  Object.values(pickedProducts).forEach((p) => options.set(p.id, p)); // 앞선 검색에서 고른 품목
  searchOptions.forEach((p) => options.set(p.id, p)); // 현재 검색 결과가 있으면 최신 값을 쓴다.

  function packingFor(productId: string) {
    const product: ProductOption | undefined = options.get(Number(productId));
    const saved = order?.items.find((i) => String(i.product_id) === productId);
    const locked = saved?.units_per_box != null; // 기존 박스 줄은 품목 설정 변경·해제 이후에도 당시 값을 쓴다
    return {
      locked, product,
      units: saved?.units_per_box ?? product?.units_per_box,
      price: saved?.box_unit_price ?? product?.box_unit_cost,
    };
  }

  function setLine(index: number, patch: Partial<Line>) {
    setLines((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row))); // 그 줄만 바꾼다
  }

  // 박스 단위가 바뀔 때 이전 수량을 적용하지 않도록 입력값을 비운다.
  function pickProduct(index: number, productId: string) {
    const { product, units } = packingFor(productId);
    if (product?.is_active) setPickedProducts((picked) => ({ ...picked, [product.id]: product }));
    const box = units != null;
    setLine(index, { product_id: productId, unit_price: String(product?.unit_cost ?? ""), box,
      ...(box || lines[index].box ? { quantity: "" } : {}) });
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    const items = lines.map((l) => ({
      product_id: num(l.product_id),
      ...(l.box ? { box_quantity: num(l.quantity) } : { quantity: num(l.quantity), unit_price: num(l.unit_price) }),
    })); // 서버는 보낸 단위에 맞춰 발주량과 당시 값을 저장한다
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

  const estimatedAmount = lines.reduce((sum, line) => {
    const count = Number(line.quantity);
    const price = line.box ? packingFor(line.product_id).price : Number(line.unit_price);
    if (!Number.isSafeInteger(count) || count < 1 || price == null || !Number.isSafeInteger(price) || price < 0) return sum;
    return sum + BigInt(count) * BigInt(price); // 여러 줄의 금액을 더해도 마지막 원까지 유지한다.
  }, BigInt(0));

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

      <ProductSearch list={productList} />
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>품목*</th><th style={S.num}>수량*</th><th style={S.num}>단가(원)*</th><th></th></tr>
        </thead>
        <tbody>
          {lines.map((line, index) => {
            const { locked, product, units, price } = packingFor(line.product_id);
            const unit = product?.unit;
            const count = Number(line.quantity);
            const suffix = line.box ? "박스 수" : unit ? `${unit} 수량` : "수량";
            return (
            <tr key={index}>
              <td>
                <select required value={line.product_id} onChange={(e) => pickProduct(index, e.target.value)} aria-label={`품목 ${index + 1}`}>
                  <option value="">선택</option>
                  {product && !searchOptions.some((p) => p.id === product.id) && <option value={product.id}>{product.sku} · {product.name}</option>}
                  {searchOptions.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
                </select>
              </td>
              <td style={S.num}>
                {units != null && !locked && (
                  <select value={line.box ? "box" : "stock"} aria-label={`${index + 1}번 줄 발주 단위`}
                    onChange={(e) => setLine(index, { box: e.target.value === "box", quantity: "" })}>
                    <option value="box">박스</option>
                    <option value="stock">재고 단위 ({unit})</option>
                  </select>
                )}{" "}
                <input type="number" required min={1} step={1} max={line.box && units != null ? boxLimit(units) : MAX_ORDER_QUANTITY}
                  style={S.numInput} value={line.quantity} onChange={(e) => setLine(index, { quantity: e.target.value })}
                  aria-label={`${index + 1}번 줄 ${suffix}`} />
                {!line.box && unit && <span style={S.sub}>재고 단위 ({unit})</span>}
                {line.box && units != null && (
                  <span style={S.sub}>{count > 0 ? `${quantityLabel(count, "박스")} · 재고 ${quantityLabel(count * units, unit)}` : `1박스 · 재고 ${quantityLabel(units, unit)}`}</span>
                )}
              </td>
              <td style={S.num}>
                {line.box && price != null ? (
                  <>{price.toLocaleString("ko-KR")}원/박스
                    {count > 0 && <span style={S.sub}>합계 {(count * price).toLocaleString("ko-KR")}원</span>}
                  </>
                ) : (
                  <input type="number" required min={0} max={100_000_000} step={1} style={S.numInput}
                    value={line.unit_price} onChange={(e) => setLine(index, { unit_price: e.target.value })} aria-label={`${index + 1}번 줄 단가`} />
                )}
              </td>
              <td><button type="button" onClick={() => setLines((rows) => rows.filter((_, i) => i !== index))}>줄 삭제</button></td>
              {/* 0줄이 되면 서버가 422 (품목 줄 1개 이상)로 막는다 */}
            </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      <button type="button" onClick={() => setLines((rows) => [...rows, { ...EMPTY_LINE }])}>줄 추가</button>
      <p style={S.hint}>예상 합계 {estimatedAmount.toLocaleString("ko-KR")}원</p>

      <p style={{ ...S.buttons, marginTop: "var(--space-md)" }}>
        <button type="submit">{order ? "변경 저장" : "초안 저장"}</button>
        <Link href={order ? `/purchase-orders/${order.id}` : "/purchase-orders"} style={S.linkButtonGhost}>{order ? "발주서 상세로 돌아가기" : "발주 목록"}</Link>
      </p>
      <ErrorText error={error} labels={PO_LABELS} />
      {duplicate && <p><Link href={`/purchase-orders/${duplicate.purchase_order_id}`}>기존 발주서 {duplicate.po_number} 열기</Link></p>}
      {/* DUPLICATE_DRAFT: 문장은 위 ErrorText 가 보여주고, 여기서 기존 초안으로 가는 링크를 준다 */}
    </form>
  );
}
