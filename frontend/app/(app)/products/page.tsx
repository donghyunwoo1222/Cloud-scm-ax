"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, apiList } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일

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
type SupplierOption = { id: number; name: string; lead_time_days: number; is_active: boolean }; // 활성·비활성 공급업체 선택지

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
  const [supplierId, setSupplierId] = useState(""); // 품목 목록에서 선택한 기본 공급업체, 빈 값이면 전체
  const list = useList<Product>("/products", { default_supplier_id: supplierId }); // 검색·활성·업체 조건을 서버 쪽 나누기에 함께 보낸다
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]); // 목록 필터에 쓸 활성·비활성 공급업체
  const [form, setForm] = useState<Form>(EMPTY); // 폼 입력값
  const [editing, setEditing] = useState<Product | null>(null); // 수정 중인 품목 (null 이면 새 등록)
  const [error, setError] = useState<unknown>(null); // 저장·버튼 오류

  useEffect(() => {
    let active = true; // 화면을 닫으면 더 불러오거나 상태를 갱신하지 않는다
    async function loadSuppliers() { // 비활성 업체에 연결된 기존 품목도 찾을 수 있게 전체 업체를 모은다
      const options: SupplierOption[] = []; // 서버에서 가져온 공급업체를 한 배열에 모은다
      let page = 1; // 공급업체 목록은 첫 쪽부터 읽는다
      while (active) { // 선택지에 100번째 이후 업체도 포함한다
        const result = await apiList<SupplierOption>(`/suppliers?page_size=100&include_inactive=true&page=${page}`); // 비활성 포함 목록 한 쪽
        options.push(...result.data); // 이번 쪽의 업체를 뒤에 붙인다
        if (page * result.meta.page_size >= result.meta.total) break; // 전체 개수만큼 읽었으면 멈춘다
        page += 1; // 다음 쪽으로 이동한다
      } // 모든 선택지를 모은다
      if (active) setSuppliers(options); // 화면이 열려 있을 때만 선택지를 바꾼다
    } // 공급업체 목록 불러오기를 정의한다
    loadSuppliers().catch((e) => { if (active) setError(e); }); // 공급업체를 못 불러오면 기존 오류 영역에 표시한다
    return () => { active = false; }; // 화면을 닫으면 남은 요청 결과를 무시한다
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
  const activeSuppliers = suppliers.filter((s) => s.is_active); // 등록·수정 폼에서 새로 고를 수 있는 업체만 남긴다
  const currentMissing = editing && !activeSuppliers.some((s) => s.id === editing.default_supplier.id) ? editing.default_supplier : null; // 기존 연결은 수정 폼에 보여준다

  return (
    <section>
      <h1>품목</h1>

      <form onSubmit={save} style={S.formGrid}>
        {/* 등록·수정 폼 */}
        <label>SKU* <input value={form.sku} onChange={(e) => set("sku", e.target.value)} /></label>
        <label>품목명* <input value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>단위* <input value={form.unit} onChange={(e) => set("unit", e.target.value)} placeholder="개, 박스" /></label>
        <label>단가(원)* <input type="number" value={form.unit_cost} onChange={(e) => set("unit_cost", e.target.value)} /></label>
        <label>안전재고 <input type="number" value={form.safety_stock} onChange={(e) => set("safety_stock", e.target.value)} /></label>
        <label>
          기본 공급업체*
          <select value={form.default_supplier_id} onChange={(e) => set("default_supplier_id", e.target.value)} style={S.block}>
            <option value="">선택하세요</option>
            {currentMissing && <option value={currentMissing.id}>{currentMissing.name} (비활성, 현재 값)</option>}
            {activeSuppliers.map((s) => ( // 새 연결은 활성 공급업체만 가능하다
              <option key={s.id} value={s.id}>
                {s.name} (리드타임 {s.lead_time_days}일)
              </option>
            ))}
          </select>
        </label>
        <div style={S.buttons}>
          <button type="submit">{editing === null ? "등록" : "수정 저장"}</button>
          {editing !== null && <button type="button" onClick={reset}>취소</button>}
        </div>
      </form>
      <ErrorText error={error} labels={LABELS} />

      {/* 검색·기본 공급업체·비활성 포함을 표 위 한 줄에 묶는다. */}
      <ListControls placeholder="SKU·품목명 검색" includeInactive={list.includeInactive} onSearch={list.search} onToggleInactive={list.toggleInactive}
        tableFilter={(
          // 업체를 바꾸면 첫 쪽으로 이동해 새 조건의 결과를 표시한다.
          <select aria-label="기본 공급업체 필터" style={{ maxWidth: "100%" }} value={supplierId} onChange={(event) => { setSupplierId(event.target.value); list.setPage(1); }}>
            <option value="">전체 공급업체</option>{/* 기본값은 업체를 제한하지 않는다. */}
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}{s.is_active ? "" : " (비활성)"}</option>)}{/* 기존 품목을 찾을 수 있도록 비활성 업체도 보여준다. */}
          </select>
        )}
      />
      <ErrorText error={list.error} />
      <div style={S.tableBox}>
      <table style={{ ...S.table, marginTop: 0 }}>
        <thead>
          <tr style={S.headRow}>
            <th>SKU</th><th>품목명</th><th>단위</th><th style={S.num}>단가</th><th style={S.num}>안전재고</th><th>기본 공급업체</th><th style={S.num}>리드타임</th><th>상태</th><th></th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((p) => (
            <tr key={p.id} style={bodyRow(p.is_active)}>
              {/* 비활성 행은 흐리게 */}
              <td style={S.nowrap}>{p.sku}</td>
              <td>{p.name}</td>
              <td>{p.unit}</td>
              <td style={S.num}>{p.unit_cost.toLocaleString()}원</td>
              {/* 5000 → 5,000원 */}
              <td style={S.num}>{p.safety_stock}</td>
              <td>{p.default_supplier.name}</td>
              <td style={S.num}>{p.default_supplier.lead_time_days}일</td>
              <td style={S.nowrap}>{p.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}</td>
              <td style={S.nowrap}>
                <button type="button" onClick={() => startEdit(p)}>수정</button>{" "}
                {p.is_active
                  ? <button type="button" onClick={() => setActive(p, false)}>비활성</button>
                  : <button type="button" onClick={() => setActive(p, true)}>다시 활성</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {list.meta?.total === 0 && <p style={S.empty}>조건에 맞는 품목이 없습니다.</p>}{/* 검색이나 필터 결과가 없을 때 안내한다. */}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
