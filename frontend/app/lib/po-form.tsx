"use client"; // 입력을 다루는 폼이라 브라우저에서 실행

import Link from "next/link"; // 기존 발주서로 가는 링크
import { useRouter } from "next/navigation"; // 저장 후 상세 화면으로 이동
import { FormEvent, useEffect, useRef, useState } from "react"; // 폼 제출, 최초 조회, 줄 번호와 상태

import { api, ApiError, apiList, apiListAll } from "./api"; // 공통 API 호출 함수, 서버 오류
import { Field } from "./field"; // 모바일에서 라벨이 테두리에 걸리는 입력 항목
import { ErrorText } from "./list"; // 서버 오류 표시
import { optionSummary } from "./options"; // 고른 품목의 옵션 요약
import { boxLimit, MAX_ORDER_QUANTITY, PO_LABELS, PurchaseOrder, unitConversion } from "./po"; // 발주서와 발주단위 환산 표시
import { ProductOption, ProductPicker } from "./product-picker"; // 발주 줄에서 품목을 검색해 바로 선택한다
import { S } from "./styles"; // 화면 공통 스타일

type Option = { id: number; name: string }; // 공급업체 선택지
type Line = { key: number; product_id: string; quantity: string; unit_price: string; box: boolean }; // 줄 번호와 입력값

const EMPTY_LINE: Line = { key: 0, product_id: "", quantity: "", unit_price: "", box: false }; // 빈 줄
const num = (v: string) => (v === "" ? null : Number(v)); // "10" → 10, 비우면 null (서버가 422 로 막는다. 1 이상·0 이상 검사는 서버가 한다)

// 발주서 작성·수정 폼 하나. order 가 있으면 수정(DRAFT 의 items 전체 교체), 없으면 새 작성
export function PoForm({ order }: { order?: PurchaseOrder }) {
  const router = useRouter(); // 저장 후 이동
  const [suppliers, setSuppliers] = useState<Option[]>([]); // 활성 공급업체 (작성할 때만 고른다)
  const [pickedProducts, setPickedProducts] = useState<Record<number, ProductOption>>({}); // 검색이 바뀌어도 고른 품목과 입수를 유지한다.
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체
  const [dueDate, setDueDate] = useState(order?.due_date ?? ""); // 약속 납기
  const [memo, setMemo] = useState(order?.memo ?? ""); // 메모
  const [deliveryAddress, setDeliveryAddress] = useState(order?.delivery_address ?? ""); // 납품장소 (비우면 문서에 회사 주소)
  const [paymentTerms, setPaymentTerms] = useState(order?.payment_terms ?? ""); // 지불조건 (새 발주서는 서버가 공급업체 기본값을 채운다)
  const nextLineKey = useRef(order?.items.length ?? 1); // 앞 줄을 지워도 다른 줄의 검색 상태가 섞이지 않는다
  const [lines, setLines] = useState<Line[]>(
    order ? order.items.map((i, key) => ({
      key,
      product_id: String(i.product_id), quantity: String(i.box_quantity ?? i.quantity),
      unit_price: String(i.unit_price), box: i.box_quantity != null,
    })) : [{ ...EMPTY_LINE }],
  ); // 품목 줄들 (수정이면 지금 줄들로 시작)
  const [error, setError] = useState<unknown>(null); // 저장 오류 (입력값은 지우지 않는다)
  const [busy, setBusy] = useState(false); // 저장 중이면 버튼을 잠그고 글자를 바꾼다
  const [bulkBusy, setBulkBusy] = useState(false); // 기본 품목을 불러오는 중이면 버튼을 잠근다
  const [notice, setNotice] = useState(""); // 일괄 추가 결과 안내 (추가한 줄 수·건너뜀)
  const [checked, setChecked] = useState(false); // 저장을 한 번 시도했는지 (수량 빈 줄 안내를 그때부터 보인다)
  const sending = useRef(false); // 상태값은 다음 화면 갱신 뒤에야 바뀌어 더블클릭을 못 막으므로, 즉시 바뀌는 ref 로 한 번 더 막는다 (#190)

  useEffect(() => {
    if (!order) apiListAll<Option>("/suppliers").then(setSuppliers).catch(setError); // 활성 업체를 100개씩 끝까지 읽는다
    else apiList<ProductOption>("/products").then((r) => setPickedProducts((picked) => ({
      ...Object.fromEntries(r.data.map((p) => [p.id, p])), ...picked,
    }))).catch(setError); // 기존 작성 중 품목의 포장 설정을 첫 목록에서 보완한다
  }, [order]);

  // 선택 상자의 품목: 활성 품목 + (수정일 때) 이미 든 품목이 지금 비활성이어도 이름이 보이게 함께 넣는다
  const options = new Map<number, ProductOption>((order?.items ?? []).map((i) => [i.product_id, {
    id: i.product_id, sku: i.product_sku, name: i.product_name, unit_cost: i.unit_price, unit: i.unit, is_active: false,
    color: i.color, size: i.size, spec: i.spec,
  }]));
  Object.values(pickedProducts).forEach((p) => options.set(p.id, p)); // 앞선 검색에서 고른 품목

  function packingFor(productId: string, product = options.get(Number(productId))) {
    const saved = order?.items.find((i) => String(i.product_id) === productId);
    const locked = saved?.units_per_box != null; // 기존 박스 줄은 품목 설정 변경·해제 이후에도 당시 값을 쓴다
    return {
      locked, product,
      units: saved?.units_per_box ?? product?.units_per_box,
      price: saved?.box_unit_price ?? product?.box_unit_cost,
      orderUnit: (locked ? saved?.order_unit : product?.order_unit) ?? "박스", // 기존 박스 줄은 발주 당시 이름
      moq: saved ? saved.min_order_units : product?.min_order_units, // 최소 주문량: 기존 줄은 발주 당시 값 (#194)
    };
  }

  function setLine(index: number, patch: Partial<Line>) {
    setLines((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row))); // 그 줄만 바꾼다
  }

  // 박스 단위가 바뀔 때 이전 수량을 적용하지 않도록 입력값을 비운다.
  function pickProduct(index: number, product: ProductOption) {
    const productId = String(product.id);
    const { units } = packingFor(productId, product);
    setPickedProducts((picked) => ({ ...picked, [product.id]: product }));
    if (lines[index].product_id === productId) return; // 같은 품목을 재선택해도 작성한 단가·수량은 보존한다
    const box = units != null;
    setLine(index, { product_id: productId, unit_price: String(product.unit_cost), box,
      ...(box || lines[index].box ? { quantity: "" } : {}) });
  }

  const targetSupplier = order ? String(order.supplier_id) : supplierId; // 기본 품목을 가져올 공급업체 (수정이면 발주서의 업체)
  const pickedIds = new Set(lines.map((l) => Number(l.product_id)).filter(Boolean)); // 이미 담은 품목 번호 (선택 결과 표시용)
  const emptyRows = lines.flatMap((l, i) => (Number(l.quantity) >= 1 ? [] : [i + 1])); // 수량이 비었거나 0인 줄 번호 (1부터)
  const quantityProblem = checked && emptyRows.length ? `수량을 입력해 주세요: ${emptyRows.map((n) => `${n}번 줄`).join(", ")}` : ""; // 제출을 시도한 뒤에만 보이고, 고치면 바로 사라진다

  // 공급업체의 기본 품목(default_supplier_id 가 그 업체인 활성 품목)을 줄로 한꺼번에 추가한다 (#195)
  async function addDefaultItems() {
    if (!targetSupplier || bulkBusy) return;
    setBulkBusy(true);
    setNotice("");
    try {
      const [products, recs] = await Promise.all([
        apiListAll<ProductOption>(`/products?default_supplier_id=${targetSupplier}`), // 100개씩 끝까지 읽는다. 비활성·다른 회사 품목은 서버가 뺀다
        api<{ items: { product_id: number; supplier_id: number; recommended_order_units: number }[] }>("/recommendations"), // 추천 전체를 받아 화면에서 거른다 (서버 필터 없음)
      ]);
      const recOf = new Map(recs.items.filter((r) => r.supplier_id === Number(targetSupplier)).map((r) => [r.product_id, r.recommended_order_units]));
      const fresh = products.filter((p) => !pickedIds.has(p.id)); // 이미 있는 줄은 중복으로 넣지 않는다
      const skipped = products.length - fresh.length;
      fresh.sort((a, b) => Number(recOf.has(b.id)) - Number(recOf.has(a.id))); // 추천이 있는 품목을 위로 (나머지 순서는 그대로)
      if (fresh.length >= 20 && !window.confirm(`이 공급업체의 품목 ${fresh.length}개를 추가합니다. 진행할까요?`)) return; // 취소하면 아무것도 추가하지 않는다
      const added = fresh.map((p): Line => {
        const { units } = packingFor(String(p.id), p);
        const rec = recOf.get(p.id); // 추천 수량: 발주단위·최소 주문량까지 올림한 값, 없으면 비워 둔다
        return { key: nextLineKey.current++, product_id: String(p.id), unit_price: String(p.unit_cost), box: units != null, quantity: rec != null ? String(rec) : "" };
      });
      setPickedProducts((picked) => ({ ...picked, ...Object.fromEntries(fresh.map((p) => [p.id, p])) }));
      setLines((rows) => [...rows.filter((l) => l.product_id !== ""), ...added]); // 품목을 안 고른 빈 줄은 지우고 채운다
      setNotice([
        `${added.length}줄을 추가했습니다.`,
        skipped ? `${skipped}개는 이미 있어 건너뜁니다.` : "",
      ].filter(Boolean).join(" "));
    } catch (e) {
      setError(e);
    } finally {
      setBulkBusy(false);
    }
  }

  // 저장 전 수량 검사: 비었거나 0인 줄이 있으면 막고 어느 줄인지 보여 준다. 제출 버튼 클릭과 submit 양쪽에서 쓴다
  function blockEmptyQuantity() {
    if (!emptyRows.length) return false;
    setChecked(true);
    document.querySelector<HTMLInputElement>(`[data-qty-row="${emptyRows[0]}"]`)?.focus(); // 첫 문제 줄로 이동
    return true;
  }

  async function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    if (sending.current) return; // 이미 저장 중이면 두 번째 제출은 버린다
    if (blockEmptyQuantity()) return;
    const items = lines.map((l) => ({
      product_id: num(l.product_id),
      ...(l.box ? { box_quantity: num(l.quantity) } : { quantity: num(l.quantity), unit_price: num(l.unit_price) }),
    })); // 서버는 보낸 단위에 맞춰 발주량과 당시 값을 저장한다
    const belowMoq = lines.flatMap((l) => {
      const { product, moq, orderUnit } = packingFor(l.product_id);
      const count = Number(l.quantity);
      const unit = l.box ? orderUnit : product?.unit ?? "";
      return moq != null && count >= 1 && count < moq ? [`- ${product?.name ?? "품목"}: 최소 ${moq}${unit}, 입력 ${count}${unit}`] : [];
    }); // 최소 주문량보다 적은 줄 (막지 않고 확인만 받는다. 공급업체와 협의한 예외가 있을 수 있다, #194)
    if (belowMoq.length && !window.confirm(`최소 주문량보다 적은 품목이 있습니다.\n${belowMoq.join("\n")}\n그대로 저장할까요?`)) return;
    sending.current = true; // 확인창을 통과한 뒤 즉시 잠금 (취소하면 잠그지 않는다)
    setBusy(true);
    try {
      const saved = order
        ? await api<PurchaseOrder>(`/purchase-orders/${order.id}`, { method: "PATCH", body: { due_date: dueDate || null, memo: memo || null, delivery_address: deliveryAddress || null, payment_terms: paymentTerms || null, items } }) // 수정: items 전체 교체
        : await api<PurchaseOrder>("/purchase-orders", { method: "POST", body: { supplier_id: num(supplierId), due_date: dueDate || null, memo: memo || null, delivery_address: deliveryAddress || null, payment_terms: paymentTerms || null, items } }); // 작성
      router.push(`/purchase-orders/${saved.id}`); // 저장되면 상세 화면으로 (화면을 떠나므로 잠금은 풀지 않는다: 이동 중 클릭으로 한 장 더 생기지 않게)
    } catch (e) {
      setError(e); // 서버 문장 그대로 보여주고 입력값은 그대로 둔다
      sending.current = false; // 실패하면 고쳐서 다시 누를 수 있게 푼다
      setBusy(false);
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
      <div className="form-compact field-form" style={S.formGrid}>
        {order ? (
          <p>공급업체: {order.supplier_name} (바꿀 수 없습니다. 다른 업체는 새 발주서로 작성하세요)</p>
        ) : (
          <Field label="공급업체*" className="field-half">
            <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} style={S.block}>
              <option value="">선택</option>
              {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="약속 납기" className="field-half"><input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} /></Field>
        <Field label="납품장소" className="field-half"><input value={deliveryAddress} maxLength={200} placeholder="비우면 회사 주소" onChange={(e) => setDeliveryAddress(e.target.value)} /></Field>
        <Field label="지불조건" className="field-half"><input value={paymentTerms} maxLength={200} placeholder={order ? "" : "비우면 공급업체 기본값"} onChange={(e) => setPaymentTerms(e.target.value)} /></Field>
        <Field label="메모"><input value={memo} onChange={(e) => setMemo(e.target.value)} /></Field>
      </div>

      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>품목*</th><th style={S.num}>수량*</th><th style={S.num}>단가(원)*</th><th></th></tr>
        </thead>
        <tbody>
          {lines.map((line, index) => {
            const { product, units, price, orderUnit, moq } = packingFor(line.product_id);
            const unit = product?.unit;
            const count = Number(line.quantity);
            const suffix = line.box ? `${orderUnit} 수` : unit ? `${unit} 수량` : "수량";
            const summary = product ? optionSummary(product) : ""; // 옵션이 없으면 빈 글자
            return (
            <tr key={line.key}>
              <td style={{ minWidth: 220 }}>
                <ProductPicker label={`품목 ${index + 1}`} value={product} pickedIds={pickedIds} onSelect={(picked) => pickProduct(index, picked)} />
                {(summary || line.box) && <span style={S.sub}>{[summary, line.box && `발주단위 ${orderUnit}`].filter(Boolean).join(" · ")}</span>}
                {/* 고른 품목의 옵션과 발주단위를 자동으로 보여 준다 (단위는 품목 설정을 따르고 고를 수 없다) */}
              </td>
              <td style={S.num}>
                <input type="number" inputMode="numeric" required min={1} step={1} max={line.box && units != null ? boxLimit(units) : MAX_ORDER_QUANTITY}
                  style={S.numInput} value={line.quantity} onChange={(e) => setLine(index, { quantity: e.target.value })}
                  data-qty-row={index + 1} aria-invalid={checked && !(count >= 1)} aria-label={`${index + 1}번 줄 ${suffix}`} />
                {line.box && <> {orderUnit}</>}{/* 단위 이름은 입력이 아니라 표시만 한다 */}
                {!line.box && unit && <span style={S.sub}>재고 단위 ({unit})</span>}
                {line.box && units != null && unit && (
                  <span style={S.sub}>{unitConversion(count > 0 ? count : 1, orderUnit, units, unit, "=")}</span>
                )}{/* 입력 즉시 "3BOX = 300EA" (비어 있으면 "1BOX = 100EA") */}
                {moq != null && (
                  <span style={count >= 1 && count < moq ? { ...S.sub, ...S.error } : S.sub}>
                    최소 주문량 {moq}{line.box ? orderUnit : unit}
                  </span>
                )}{/* 적게 입력하면 경고 색. 저장 때 확인창으로 한 번 더 묻는다 */}
              </td>
              <td style={S.num}>
                {line.box && price != null ? (
                  <>{price.toLocaleString("ko-KR")}원/{orderUnit}
                    {count > 0 && <span style={S.sub}>합계 {(count * price).toLocaleString("ko-KR")}원</span>}
                  </>
                ) : (
                  <input type="number" inputMode="numeric" required min={0} max={100_000_000} step={1} style={S.numInput}
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
      <button type="button" onClick={() => {
        const key = nextLineKey.current++;
        setLines((rows) => [...rows, { ...EMPTY_LINE, key }]);
      }}>줄 추가</button>
      {targetSupplier && <button type="button" disabled={bulkBusy} onClick={addDefaultItems}>{bulkBusy ? "불러오는 중…" : "기본 품목 추가"}</button>}
      {/* 이 공급업체가 기본 공급업체인 활성 품목을 한 번에 추가한다. 추천이 있으면 수량도 채운다 */}
      {emptyRows.length > 0 && (
        <button type="button" onClick={() => setLines((rows) => rows.filter((l) => Number(l.quantity) >= 1))}>수량 빈 줄 모두 삭제</button>
      )}{/* 수량이 비었거나 0인 줄만 지운다. 저장할 때 자동으로 빼지는 않는다 */}
      {notice && <p role="status" style={S.hint}>{notice}</p>}
      {quantityProblem && <p role="alert" style={S.error}>{quantityProblem}</p>}
      <p style={S.hint}>예상 합계 {estimatedAmount.toLocaleString("ko-KR")}원</p>

      <p style={{ ...S.buttons, marginTop: "var(--space-md)" }}>
        <button type="submit" disabled={busy} onClick={(e) => { if (blockEmptyQuantity()) e.preventDefault(); }}>{busy ? "저장 중…" : order ? "변경 저장" : "초안 저장"}</button>
        <Link href={order ? `/purchase-orders/${order.id}` : "/purchase-orders"} style={S.linkButtonGhost}>{order ? "발주서 상세로 돌아가기" : "발주 목록"}</Link>
      </p>
      <ErrorText error={error} labels={PO_LABELS} />
      {duplicate && <p><Link href={`/purchase-orders/${duplicate.purchase_order_id}`}>기존 발주서 {duplicate.po_number} 열기</Link></p>}
      {/* DUPLICATE_DRAFT: 문장은 위 ErrorText 가 보여주고, 여기서 기존 초안으로 가는 링크를 준다 */}
    </form>
  );
}
