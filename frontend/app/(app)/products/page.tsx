"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 공급업체와 첫 입고로 이동한다.
import { FormEvent, useEffect, useRef, useState } from "react"; // 폼 제출, 처음 한 번 실행, 상태

import { api, apiList } from "../../lib/api"; // 공통 API 호출 함수
import { Field } from "../../lib/field"; // 모바일에서 라벨이 테두리에 걸치는 입력 항목
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { optionSummary } from "../../lib/options"; // 옵션 요약 ("검정 / M")
import { unitConversion } from "../../lib/po"; // 발주단위 환산 미리보기
import { StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/products 의 한 행 (재고 숫자는 없다, #31)
type Product = {
  id: number; // 번호
  sku: string; // 품목 코드 (서버가 대문자로 저장)
  name: string; // 품목명
  unit: string; // 단위
  color: string | null; size: string | null; spec: string | null; // 옵션 (없으면 null)
  group_code: string | null; // 그룹 코드 (서버가 대문자로 저장)
  unit_cost: number; // 단가(원)
  units_per_box: number | null; // 박스 한 개의 재고 단위 수량
  box_unit_cost: number | null; // 박스당 구매 단가
  order_unit: string; // 발주단위 이름 (박스 설정이 없으면 재고 단위)
  min_order_units: number | null; // 최소 주문량(발주단위 수), 없으면 제한 없음 (#194)
  safety_stock: number; // 안전재고
  is_active: boolean; // 활성 여부
  default_supplier: { id: number; name: string; lead_time_days: number }; // 기본 공급업체 요약
};
type SupplierOption = { id: number; name: string; lead_time_days: number; is_active: boolean }; // 활성·비활성 공급업체 선택지

// 폼 입력값 (모두 글자로 다루고 보낼 때 바꾼다)
const EMPTY = { sku: "", name: "", unit: "", color: "", size: "", spec: "", group_code: "", unit_cost: "", safety_stock: "0", default_supplier_id: "", units_per_box: "", box_unit_cost: "", order_unit: "", min_order_units: "" };
type Form = typeof EMPTY;

// 오류 details 의 칸 이름 → 화면 이름
const LABELS = { sku: "SKU", name: "품목명", unit: "재고 단위", color: "색상", size: "사이즈", spec: "규격", group_code: "그룹 코드", unit_cost: "재고 단위 단가", safety_stock: "안전재고", default_supplier_id: "기본 공급업체", units_per_box: "환산계수", box_unit_cost: "발주단위 단가", order_unit: "발주단위", min_order_units: "최소 주문량" };

// 폼 값 → 서버로 보낼 본문 (숫자 칸은 숫자로, 비우면 null → 서버가 422. 0 이상 정수 검사는 서버가 한다)
function toBody(form: Form) {
  const num = (v: string) => (v === "" ? null : Number(v)); // "5000" → 5000
  return {
    sku: form.sku, // 공백 제거·대문자는 서버가 한다 (ts-bk-m → TS-BK-M)
    name: form.name,
    unit: form.unit,
    color: form.color, // 공백 제거·빈 글자 → null 은 서버가 한다
    size: form.size,
    spec: form.spec,
    group_code: form.group_code, // 대문자 변환도 서버가 한다
    unit_cost: num(form.unit_cost),
    safety_stock: num(form.safety_stock),
    default_supplier_id: num(form.default_supplier_id),
    units_per_box: num(form.units_per_box),
    box_unit_cost: num(form.box_unit_cost),
    order_unit: form.units_per_box === "" ? null : form.order_unit.trim() || null, // 발주단위 설정이 없으면 보내지 않는다(서버 422). 비우면 서버가 "박스"
    min_order_units: num(form.min_order_units), // 비우면 null = 제한 없음
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
  const registration = useRef<HTMLDetailsElement>(null); // 목록에서 수정할 때 같은 폼을 연다.
  const [created, setCreated] = useState(false); // 첫 입고로 바로 이어갈 수 있게 한다.
  const [boxOpen, setBoxOpen] = useState(false); // 모바일에서 "박스 발주 설정"을 펼쳤는지 (데스크톱은 항상 보인다)
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
      color: p.color ?? "", size: p.size ?? "", spec: p.spec ?? "", group_code: p.group_code ?? "", // 옵션이 없으면 빈 칸
      safety_stock: String(p.safety_stock), default_supplier_id: String(p.default_supplier.id),
      units_per_box: p.units_per_box == null ? "" : String(p.units_per_box),
      box_unit_cost: p.box_unit_cost == null ? "" : String(p.box_unit_cost),
      order_unit: p.units_per_box == null ? "" : p.order_unit, // 설정이 없으면 서버가 재고 단위를 주므로 빈 칸으로
      min_order_units: p.min_order_units == null ? "" : String(p.min_order_units),
    }; // 품목 → 폼 값
  }

  function startEdit(p: Product) {
    const form = registration.current;
    if (form) {
      form.open = true; // 펼침은 CSS 가 부드럽게 움직인다(.smooth-details)
      const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches; // 움직임 줄이기를 켠 사람에게는 바로 이동
      form.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" }); // 폼이 있는 위쪽으로 부드럽게 올라간다
      // 펼치는 동안에는 내용이 아직 숨겨져 있어 바로 포커스가 안 먹으므로 다음 화면 갱신 때 준다(스크롤은 다시 튀지 않게 막는다)
      requestAnimationFrame(() => form.querySelector("input")?.focus({ preventScroll: true }));
    }
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
      setCreated(editing === null);
      reset(); // 성공하면 폼 비우기
      if (registration.current) registration.current.open = false;
      setError(null);
      await list.reload(); // 목록 다시 불러오기
    } catch (e) {
      setError(e); // 서버 message 그대로 (예: SKU 중복, 비활성 업체 선택)
    }
  }

  async function setActive(p: Product, active: boolean) {
    if (!active && !window.confirm(`${p.name}을 비활성화할까요? 새 발주와 추천에서는 제외되며 기존 이력은 남습니다.`)) return;
    try {
      await api(`/products/${p.id}`, { method: "PATCH", body: { is_active: active } }); // 비활성·다시 활성 (삭제는 없다)
      setError(null);
      reset(); // 수정 폼 안에서 바꾸므로 폼을 닫는다
      if (registration.current) registration.current.open = false;
      await list.reload();
    } catch (e) {
      setError(e);
    }
  }

  // 수정 중인 품목의 기본 공급업체가 비활성이라 선택지에 없으면, 지금 값으로 한 줄 보여준다 (새로 고를 수는 없음)
  const activeSuppliers = suppliers.filter((s) => s.is_active); // 등록·수정 폼에서 새로 고를 수 있는 업체만 남긴다
  const currentMissing = editing && !activeSuppliers.some((s) => s.id === editing.default_supplier.id) ? editing.default_supplier : null; // 기존 연결은 수정 폼에 보여준다

  const boxShown = boxOpen || form.units_per_box !== "" || form.box_unit_cost !== "" || form.order_unit !== "" || form.min_order_units !== ""; // 값이 하나라도 있으면 펼친다
  const factor = Number(form.units_per_box); // 미리보기용 환산계수
  const moq = Number(form.min_order_units); // 미리보기용 최소 주문량
  const boxed = Number.isInteger(factor) && factor >= 1; // 발주단위 설정이 있으면 발주단위, 없으면 재고 단위로 센다
  return (
    <section>
      <h1>품목</h1>

      {created && <p role="status" style={S.ok}>품목을 등록했습니다. <Link href="/receipts#direct-receipt">입고 등록으로 이동</Link></p>}
      <details ref={registration} className="smooth-details" style={S.sectionCard}>
      <summary>{editing ? `${editing.name} 수정` : "품목 등록"}</summary>
      {!editing && activeSuppliers.length === 0 && <p>기본 공급업체가 필요합니다. <Link href="/suppliers">공급업체 등록</Link></p>}
      <form className="form-compact field-form" data-box-open={boxShown} onSubmit={save} style={S.formGrid}>
        {/* 등록·수정 폼. 모바일에서는 짧은 항목을 두 칸씩 묶고 박스 설정은 접는다(값이 하나라도 있으면 펼친다) */}
        <Field label="SKU*" className="field-half fld-sku"><input value={form.sku} onChange={(e) => set("sku", e.target.value)} /></Field>
        <Field label="품목명*" className="fld-name"><input value={form.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="색상" className="field-half fld-opt"><input value={form.color} onChange={(e) => set("color", e.target.value)} maxLength={50} placeholder="검정" /></Field>
        <Field label="사이즈" className="field-half fld-opt"><input value={form.size} onChange={(e) => set("size", e.target.value)} maxLength={50} placeholder="M" /></Field>
        <Field label="규격" className="field-half fld-opt"><input value={form.spec} onChange={(e) => set("spec", e.target.value)} maxLength={50} placeholder="2L, 30롤" /></Field>
        <Field label="그룹 코드" className="field-half fld-opt"><input value={form.group_code} onChange={(e) => set("group_code", e.target.value)} maxLength={50} placeholder="TS-BASIC" /></Field>
        {/* 옵션 4칸은 모두 선택. 같은 상품의 색·사이즈·규격마다 SKU 를 따로 만들고 그룹 코드로 묶는다 */}
        <Field label="재고 단위*" className="field-half fld-unit"><input value={form.unit} onChange={(e) => set("unit", e.target.value)} placeholder="개, 병" /></Field>
        <Field label="재고 단위 단가(원)*" short="단가(원)*" className="field-half fld-cost"><input type="number" inputMode="numeric" value={form.unit_cost} onChange={(e) => set("unit_cost", e.target.value)} /></Field>
        <Field label="안전재고" className="field-half fld-safety"><input type="number" inputMode="numeric" value={form.safety_stock} onChange={(e) => set("safety_stock", e.target.value)} /></Field>
        <Field label="기본 공급업체*" className="fld-supplier"><select value={form.default_supplier_id} onChange={(e) => set("default_supplier_id", e.target.value)} style={S.block}>
            <option value="">선택하세요</option>
            {currentMissing && <option value={currentMissing.id}>{currentMissing.name} (비활성, 현재 값)</option>}
            {activeSuppliers.map((s) => ( // 새 연결은 활성 공급업체만 가능하다
              <option key={s.id} value={s.id}>
                {s.name} (리드타임 {s.lead_time_days}일)
              </option>
            ))}
          </select></Field>
        <button type="button" className="box-toggle" aria-expanded={boxShown}
          onClick={() => setBoxOpen(!boxOpen)}>발주단위 설정 (선택)<span aria-hidden="true">{boxShown ? "접기" : "펼치기"}</span></button>
        {/* 모바일 전용 접기 버튼: 데스크톱에서는 CSS 로 숨긴다 */}
        <Field label="발주단위" className="field-half box-field"><input value={form.order_unit} onChange={(e) => set("order_unit", e.target.value)} maxLength={20} placeholder="박스, BOX, PACK"
            aria-describedby="product-box-hint" /></Field>
        <Field label="환산계수 (1발주단위당 재고 수량)" short="환산계수" className="field-half box-field"><input type="number" inputMode="numeric" min={1} max={1_000_000} step={1} required={form.box_unit_cost !== ""}
            value={form.units_per_box} onChange={(e) => set("units_per_box", e.target.value)} aria-describedby="product-box-hint" /></Field>
        <Field label="발주단위 단가(원)" short="발주단위 단가(원)" className="field-half box-field"><input type="number" inputMode="numeric" min={0} max={100_000_000} step={1} required={form.units_per_box !== ""}
            value={form.box_unit_cost} onChange={(e) => set("box_unit_cost", e.target.value)} aria-describedby="product-box-hint" /></Field>
        <Field label={`최소 주문량 (${boxed ? "발주단위" : "재고 단위"} 수)`} short="최소 주문량" className="field-half box-field"><input type="number" inputMode="numeric" min={1} max={1_000_000} step={1}
            value={form.min_order_units} onChange={(e) => set("min_order_units", e.target.value)} placeholder="비우면 제한 없음" aria-describedby="product-box-hint" /></Field>
        <p id="product-box-hint" className="box-hint" style={{ ...S.hint, flexBasis: "100%", margin: 0 }}>
          {Number.isInteger(factor) && factor >= 1 && form.unit.trim() !== "" && <strong>{unitConversion(1, form.order_unit.trim() || "박스", factor, form.unit.trim(), "=")} · </strong>}
          {/* 미리보기 예: "1BOX = 100EA" (발주단위를 비우면 서버가 "박스"로 저장한다) */}
          {Number.isInteger(moq) && moq >= 1 && form.unit.trim() !== "" && <strong>최소 {unitConversion(moq, boxed ? form.order_unit.trim() || "박스" : form.unit.trim(), boxed ? factor : 1, form.unit.trim(), "=")} · </strong>}
          {/* 최소 주문량 미리보기 예: "최소 5BOX = 500EA", 발주단위 설정이 없으면 "최소 20EA" */}
          박스·팩 등으로 구매할 때 환산계수와 단가를 채우세요. 둘 다 비워 저장하면 발주단위 설정을 해제합니다.</p>
        <div className="form-actions" style={S.buttons}>
          <button type="submit" disabled={!editing && activeSuppliers.length === 0}>{editing === null ? "등록" : "수정 저장"}</button>
          {editing !== null && <button type="button" onClick={reset}>취소</button>}
          {/* 비활성·다시 활성은 목록 표가 아니라 수정 폼 안에서만 한다 (잘못 누르기 어렵게) */}
          {editing !== null && <button type="button" onClick={() => setActive(editing, !editing.is_active)}>{editing.is_active ? "비활성" : "다시 활성"}</button>}
        </div>
      </form>
      </details>
      <ErrorText error={error} labels={LABELS} />

      {/* 검색·기본 공급업체·비활성 포함을 표 위 한 줄에 묶는다. */}
      <ListControls placeholder="품목명·SKU·옵션 검색" includeInactive={list.includeInactive} onSearch={list.search} onToggleInactive={list.toggleInactive}
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
            <th>SKU</th><th>품목명</th><th>옵션</th><th>단위</th><th style={S.num}>단가</th><th style={S.num}>안전재고</th><th>기본 공급업체</th><th style={S.num}>리드타임</th><th>상태</th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((p) => (
            <tr key={p.id} style={bodyRow(p.is_active)}>
              {/* 비활성 행은 흐리게 */}
              <td style={S.nowrap}>{p.sku}</td>
              <td><button type="button" className="text-button" aria-label={`${p.name} 수정`} onClick={() => startEdit(p)}>{p.name}</button></td>
              {/* 품목 이름을 누르면 위 수정 폼이 열린다(줄마다 수정·비활성 버튼 칸을 두지 않는다) */}
              <td>{optionSummary(p)}{p.group_code && <span style={S.sub}>그룹 {p.group_code}</span>}</td>
              {/* 옵션이 없으면 빈 칸 */}
              <td>{p.unit}</td>
              <td style={S.num}>
                {p.unit_cost.toLocaleString("ko-KR")}원
                {p.units_per_box != null && p.box_unit_cost != null && (
                  <span style={S.sub}>{p.units_per_box.toLocaleString("ko-KR")}{p.unit}/{p.order_unit} · {p.box_unit_cost.toLocaleString("ko-KR")}원/{p.order_unit}</span>
                )}
              </td>
              {/* 5000 → 5,000원 */}
              <td style={S.num}>{p.safety_stock}</td>
              <td>{p.default_supplier.name}</td>
              <td style={S.num}>{p.default_supplier.lead_time_days}일</td>
              <td style={S.nowrap}>{p.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}</td>
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
