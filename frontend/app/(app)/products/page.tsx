"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, apiList } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품

// GET /api/v1/products 의 한 행 (재고 숫자는 없다, #31)
type Product = {
  id: number; // 번호
  sku: string; // 품목 코드 (서버가 대문자로 저장)
  name: string; // 품목명
  unit: string; // 단위
  unit_cost: number; // 단가(원)
  safety_stock: number; // 안전재고
  is_active: boolean; // 활성 여부
  default_supplier: { id: number; name: string; lead_time_days: number }; // 기본 공급업체 요약
};
type SupplierOption = { id: number; name: string; lead_time_days: number }; // 선택 상자에 쓸 공급업체

// 폼 입력값 (모두 글자로 다루고 보낼 때 바꾼다)
const EMPTY = { sku: "", name: "", unit: "", unit_cost: "", safety_stock: "0", default_supplier_id: "" };
type Form = typeof EMPTY;

// 오류 details 의 칸 이름 → 화면 이름
const LABELS = { sku: "SKU", name: "품목명", unit: "단위", unit_cost: "단가", safety_stock: "안전재고", default_supplier_id: "기본 공급업체" };

// 폼 값 → 서버로 보낼 본문 (숫자 칸은 숫자로, 비우면 null → 서버가 422. 0 이상 정수 검사는 서버가 한다)
function toBody(form: Form) {
  const num = (v: string) => (v === "" ? null : Number(v)); // "5000" → 5000
  return {
    sku: form.sku, // 공백 제거·대문자는 서버가 한다 (ts-bk-m → TS-BK-M)
    name: form.name,
    unit: form.unit,
    unit_cost: num(form.unit_cost),
    safety_stock: num(form.safety_stock),
    default_supplier_id: num(form.default_supplier_id),
  };
}

// 수정 때는 바뀐 칸만 보낸다. 기본 공급업체가 나중에 비활성이 된 품목도 단가 등 다른 칸은 고칠 수 있게
// (기본 공급업체 칸을 보내면 서버가 그 업체를 다시 검사해 비활성이면 409 를 준다)
function changedFields(next: ReturnType<typeof toBody>, before: ReturnType<typeof toBody>) {
  return Object.fromEntries(
    Object.entries(next).filter(([key, value]) => before[key as keyof typeof before] !== value), // 값이 다른 칸만
  );
}

// 품목 화면 (주소 /products): 목록 + 등록·수정 폼 + 비활성·다시 활성
export default function ProductsPage() {
  const list = useList<Product>("/products"); // 목록 상태 (20개씩, 최신순, SKU·품목명 검색, 비활성 포함)
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]); // 기본 공급업체 선택지 (활성 업체만)
  const [form, setForm] = useState<Form>(EMPTY); // 폼 입력값
  const [editing, setEditing] = useState<Product | null>(null); // 수정 중인 품목 (null 이면 새 등록)
  const [error, setError] = useState<unknown>(null); // 저장·버튼 오류

  useEffect(() => {
    // 선택 상자에는 활성 공급업체만 (서버 목록의 기본값이 활성만이다)
    // shortcut: 활성 업체 100개까지만 불러온다(서버 page_size 최대). 업체가 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<SupplierOption>("/suppliers?page_size=100").then((r) => setSuppliers(r.data)).catch(setError);
  }, []);

  function set(field: keyof Form, value: string) {
    setForm({ ...form, [field]: value }); // 한 칸만 바꾼다
  }

  function formOf(p: Product): Form {
    return {
      sku: p.sku, name: p.name, unit: p.unit, unit_cost: String(p.unit_cost),
      safety_stock: String(p.safety_stock), default_supplier_id: String(p.default_supplier.id),
    }; // 품목 → 폼 값
  }

  function startEdit(p: Product) {
    setEditing(p); // 수정 모드
    setForm(formOf(p)); // 그 품목 값으로 폼 채우기
    setError(null);
  }

  function reset() {
    setEditing(null); // 새 등록 모드로
    setForm(EMPTY); // 폼 비우기
  }

  async function save(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    try {
      if (editing === null) await api("/products", { method: "POST", body: toBody(form) }); // 등록
      else {
        const body = changedFields(toBody(form), toBody(formOf(editing))); // 바뀐 칸만
        await api(`/products/${editing.id}`, { method: "PATCH", body }); // 수정
      }
      reset(); // 성공하면 폼 비우기
      setError(null);
      await list.reload(); // 목록 다시 불러오기
    } catch (e) {
      setError(e); // 서버 message 그대로 (예: SKU 중복, 비활성 업체 선택)
    }
  }

  async function setActive(p: Product, active: boolean) {
    try {
      await api(`/products/${p.id}`, { method: "PATCH", body: { is_active: active } }); // 비활성·다시 활성 (삭제는 없다)
      setError(null);
      await list.reload();
    } catch (e) {
      setError(e);
    }
  }

  // 수정 중인 품목의 기본 공급업체가 비활성이라 선택지에 없으면, 지금 값으로 한 줄 보여준다 (새로 고를 수는 없음)
  const currentMissing = editing && !suppliers.some((s) => s.id === editing.default_supplier.id) ? editing.default_supplier : null;

  return (
    <section>
      <h1>품목</h1>

      <form onSubmit={save} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.5rem", alignItems: "end", margin: "1rem 0" }}>
        {/* 등록·수정 폼 */}
        <label>SKU* <input value={form.sku} onChange={(e) => set("sku", e.target.value)} /></label>
        <label>품목명* <input value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>단위* <input value={form.unit} onChange={(e) => set("unit", e.target.value)} placeholder="개, 박스" /></label>
        <label>단가(원)* <input type="number" value={form.unit_cost} onChange={(e) => set("unit_cost", e.target.value)} /></label>
        <label>안전재고 <input type="number" value={form.safety_stock} onChange={(e) => set("safety_stock", e.target.value)} /></label>
        <label>
          기본 공급업체*
          <select value={form.default_supplier_id} onChange={(e) => set("default_supplier_id", e.target.value)} style={{ display: "block" }}>
            <option value="">선택하세요</option>
            {currentMissing && <option value={currentMissing.id}>{currentMissing.name} (비활성, 현재 값)</option>}
            {suppliers.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name} (리드타임 {s.lead_time_days}일)
              </option>
            ))}
          </select>
        </label>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <button type="submit">{editing === null ? "등록" : "수정 저장"}</button>
          {editing !== null && <button type="button" onClick={reset}>취소</button>}
        </div>
      </form>
      <ErrorText error={error} labels={LABELS} />

      <ListControls placeholder="SKU·품목명 검색" includeInactive={list.includeInactive} onSearch={list.search} onToggleInactive={list.toggleInactive} />
      <ErrorText error={list.error} />
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left" }}>
            <th>SKU</th><th>품목명</th><th>단위</th><th>단가</th><th>안전재고</th><th>기본 공급업체</th><th>리드타임</th><th>상태</th><th></th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((p) => (
            <tr key={p.id} style={{ borderTop: "1px solid #ccc", opacity: p.is_active ? 1 : 0.5 }}>
              {/* 비활성 행은 흐리게 */}
              <td>{p.sku}</td>
              <td>{p.name}</td>
              <td>{p.unit}</td>
              <td>{p.unit_cost.toLocaleString()}원</td>
              {/* 5000 → 5,000원 */}
              <td>{p.safety_stock}</td>
              <td>{p.default_supplier.name}</td>
              <td>{p.default_supplier.lead_time_days}일</td>
              <td>{p.is_active ? "활성" : "비활성"}</td>
              <td>
                <button type="button" onClick={() => startEdit(p)}>수정</button>{" "}
                {p.is_active
                  ? <button type="button" onClick={() => setActive(p, false)}>비활성</button>
                  : <button type="button" onClick={() => setActive(p, true)}>다시 활성</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {list.meta?.total === 0 && <p>{list.includeInactive ? "품목이 없습니다." : "활성 품목이 없습니다."}</p>}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
