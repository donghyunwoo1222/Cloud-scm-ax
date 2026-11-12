"use client"; // 파일 선택·열 지정 등 브라우저에서 동작하는 화면

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, apiListAll } from "../../lib/api"; // 서버 호출
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { S } from "../../lib/styles"; // 공통 스타일
import { InfoTip } from "../../lib/tip"; // 보조 설명 말풍선

// 품목 가져오기 (#189, 주소 /product-import): 파일 → 열 지정 → 미리보기 → 반영. receipt-import 와 같은 흐름이다.
// 품목 정보만 다룬다(재고 이동은 만들지 않는다). 파일의 SKU 가 이미 있으면 수정, 없으면 신규 등록.

type ColKey = "product" | "name" | "unit" | "cost" | "safety" | "order_unit" | "factor" | "box_cost" | "moq" | "color" | "size" | "spec" | "group";
type Inspect = { headers: string[]; row_count: number; suggested: Record<`${ColKey}_col`, number | null> };
type NewProduct = {
  row: number; sku: string; name: string; unit: string; unit_cost: number; safety_stock: number;
  order_unit: string | null; units_per_box: number | null; box_unit_cost: number | null; min_order_units: number | null;
  color: string | null; size: string | null; spec: string | null; group_code: string | null;
};
type Change = { field: string; label: string; old: string | number | null; new: string | number | null };
type Update = { row: number; sku: string; name: string; changes: Change[] };
type Problem = { row: number; reason: string; message: string; sku: string | null };
type Preview = {
  total_rows: number; new_count: number; update_count: number; unchanged_count: number;
  new_products: NewProduct[]; updates: Update[]; problem_count: number; problems: Problem[];
};
type Done = { created_count: number; updated_count: number; unchanged_count: number; problem_count: number; preview_changed: boolean; message: string | null };

const NONE = ""; // 선택 안 함
const REQUIRED: ColKey[] = ["product", "name", "unit", "cost"]; // 필수 열
const KEYS: ColKey[] = [...REQUIRED, "safety", "order_unit", "factor", "box_cost", "moq", "color", "size", "spec", "group"];
const EMPTY = Object.fromEntries(KEYS.map((k) => [k, NONE])) as Record<ColKey, string>;
const shown = (v: string | number | null) => (v === null || v === "" ? "없음" : typeof v === "number" ? v.toLocaleString() : v);

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [info, setInfo] = useState<Inspect | null>(null);
  const [cols, setCols] = useState(EMPTY); // 열 번호(글자) 또는 NONE
  const [suppliers, setSuppliers] = useState<{ id: number; name: string }[]>([]); // 활성 공급업체
  const [supplier, setSupplier] = useState(""); // 새 품목의 기본 공급업체
  const [preview, setPreview] = useState<Preview | null>(null);
  const [exclude, setExclude] = useState(false);
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const previewHeading = useRef<HTMLHeadingElement>(null); // 미리보기가 화면 아래에 생기므로 포커스를 옮겨 알린다
  useEffect(() => {
    if (!preview || !previewHeading.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    previewHeading.current.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    previewHeading.current.focus({ preventScroll: true });
  }, [preview]);
  const sending = useRef(false); // 더블클릭 방지 (상태값은 다음 그리기 뒤에야 바뀌므로 ref 도 함께 쓴다)

  useEffect(() => { apiListAll<{ id: number; name: string }>("/suppliers").then(setSuppliers).catch(setError); }, []);

  async function run(job: () => Promise<void>) {
    if (sending.current) return;
    sending.current = true; setBusy(true); setError(null);
    try { await job(); } catch (e) { setError(e); } finally { sending.current = false; setBusy(false); }
  }

  const form = (extra?: Record<string, string>, upload: File | null = file) => {
    const f = new FormData();
    f.append("file", upload as File);
    for (const [k, v] of Object.entries(extra ?? {})) f.append(k, v);
    return f;
  };
  const num = (v: string) => (v === NONE ? null : Number(v));
  // 확정 때만 expected_* 를 붙인다: 미리보기와 건수가 달라지면 서버가 preview_changed 로 알린다
  const options = (excludeProblems: boolean, expected?: Preview) => JSON.stringify({
    ...Object.fromEntries(KEYS.map((k) => [`${k}_col`, num(cols[k])])),
    default_supplier_id: supplier ? Number(supplier) : null, exclude_problems: excludeProblems,
    ...(expected ? { expected_new_count: expected.new_count, expected_update_count: expected.update_count } : {}),
  });
  const columnsReady = REQUIRED.every((k) => cols[k] !== NONE);

  function reset(next: File | null) {
    setFile(next); setInfo(null); setPreview(null); setDone(null); setError(null); setExclude(false); setCols(EMPTY);
  }

  const inspect = (f: File) => run(async () => {
    reset(f);
    const data = await api<Inspect>("/product-imports/inspect", { method: "POST", body: form(undefined, f) });
    setInfo(data);
    setCols(Object.fromEntries(KEYS.map((k) => [k, data.suggested[`${k}_col`] === null ? NONE : String(data.suggested[`${k}_col`])])) as Record<ColKey, string>);
  });

  const runPreview = () => run(async () => {
    setExclude(false);
    setPreview(await api<Preview>("/product-imports/preview", { method: "POST", body: form({ options: options(false) }) }));
  });

  const commit = () => run(async () => {
    if (!preview) return;
    setDone(await api<Done>("/product-imports", { method: "POST", body: form({ options: options(exclude, preview) }) }));
    setPreview(null);
  });

  const needsSupplier = (preview?.new_count ?? 0) > 0 && !supplier;
  const hasWork = preview && (preview.new_count > 0 || preview.update_count > 0);
  const canCommit = hasWork && !needsSupplier && (preview.problem_count === 0 || exclude);
  const colSelect = (label: string, k: ColKey) => (
    <label className="field" key={k}>
      <span className="field-label">{label}{REQUIRED.includes(k) ? " *" : ""}</span>
      <select value={cols[k]} disabled={busy} onChange={(e) => { setCols({ ...cols, [k]: e.target.value }); setPreview(null); }}>
        <option value={NONE}>{REQUIRED.includes(k) ? "열 선택" : "사용 안 함"}</option>
        {info?.headers.map((h, i) => <option key={i} value={i}>{h || `(${i + 1}번째 열)`}</option>)}
      </select>
    </label>
  );
  const commitLabel = [preview?.new_count ? `신규 ${preview.new_count}개 등록` : "", preview?.update_count ? `기존 ${preview.update_count}개 수정` : ""]
    .filter(Boolean).join(", ");
  // 반영 버튼이 막힌 이유를 버튼 옆에 적는다 (막힌 버튼만 보면 무엇을 해야 하는지 모른다)
  const blockReason = !preview || !hasWork ? null
    : needsSupplier ? "새 품목의 기본 공급업체를 고르면 반영할 수 있습니다"
    : preview.problem_count > 0 && !exclude ? "문제 행을 파일에서 고치거나, 제외하고 반영을 체크하세요" : null;

  return (
    <section>
      <h1>품목 가져오기</h1>
      <p style={S.hint}>
        파일 하나로 품목을 새로 등록하거나 기존 품목을 고칩니다{" "}
        <InfoTip detail="SKU(공백 제거·대문자)가 이미 있으면 수정, 없으면 새 품목입니다. 빈 칸은 '변경 없음'이라 기존 값이 지워지지 않고, 활성 여부와 기본 공급업체는 바뀌지 않습니다. 파일은 .csv·.xlsx, 5MB·5,000행 이하이고 저장하지 않습니다." />
      </p>
      <p style={S.hint}>
        이 화면은 품목 정보만 다룹니다. 기초 재고는 <Link href="/receipt-import">품목·입고 가져오기</Link>에서 입고로 입력하세요.
      </p>

      <div style={S.sectionCard}>
        <h2 style={{ marginTop: 0 }}>1. 파일 올리기</h2>
        <input key={inputKey} type="file" accept=".csv,.xlsx" disabled={busy} aria-label="품목 파일"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void inspect(f); else reset(null); }} />
        <p style={{ ...S.hint, marginBottom: 0 }}>
          {info ? `${file?.name} · 데이터 ${info.row_count.toLocaleString()}행 · ` : ""}템플릿 내려받기:{" "}
          <a href="/api/v1/import-templates/products.xlsx" download>엑셀</a> · <a href="/api/v1/import-templates/products.csv" download>CSV</a>
        </p>
      </div>

      {info && !done && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 열 지정</h2>
          <p style={S.hint}>
            머리글이 비슷한 열은 미리 골라 두었습니다. 맞는지 확인하세요{" "}
            <InfoTip detail="환산계수와 발주단위 단가는 함께 있어야 하고, 발주단위 이름은 환산계수가 있을 때만 쓸 수 있습니다. 기존 품목은 파일에 없는 값과 합쳐서 검사합니다." />
          </p>
          <h3 style={SUB}>필수</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("SKU", "product")}
            {colSelect("품목명", "name")}
            {colSelect("기본단위", "unit")}
            {colSelect("구매단가(원)", "cost")}
          </div>
          <h3 style={SUB}>선택 <span style={{ ...S.hint, fontWeight: 400 }}>(고르지 않거나 칸이 비면 변경 없음)</span></h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("안전재고", "safety")}
            {colSelect("발주단위 이름", "order_unit")}
            {colSelect("환산계수", "factor")}
            {colSelect("발주단위 단가", "box_cost")}
            {colSelect("최소 주문량", "moq")}
            {colSelect("색상", "color")}
            {colSelect("사이즈", "size")}
            {colSelect("규격", "spec")}
            {colSelect("그룹 코드", "group")}
          </div>
          <div style={BLOCK}>
            <button type="button" className="primary-action" disabled={busy || !columnsReady} onClick={() => void runPreview()}>
              {busy ? "확인 중…" : "미리보기"}
            </button>
          </div>
        </div>
      )}

      {preview && !done && (
        <div style={S.sectionCard}>
          <h2 ref={previewHeading} tabIndex={-1} style={{ marginTop: 0, outline: "none" }}>3. 미리보기</h2>
          <p style={{ margin: 0, fontVariantNumeric: "tabular-nums" }}>
            <strong>신규 {preview.new_count.toLocaleString()}개 · 수정 {preview.update_count.toLocaleString()}개</strong>
            {" "}· 변경 없음 {preview.unchanged_count.toLocaleString()}개 · 문제 {preview.problem_count.toLocaleString()}건
          </p>
          {hasWork && <p style={{ ...S.hint, margin: "var(--space-xs) 0 0" }}>반영하면 신규 {preview.new_count}개를 등록하고 기존 {preview.update_count}개를 수정합니다. 기존 품목은 파일에 값이 있는 칸만 바뀝니다.</p>}
          {!hasWork && preview.unchanged_count > 0 && preview.problem_count === 0 && (
            <p role="status" style={{ ...S.ok, ...BLOCK }}>파일의 모든 품목이 이미 같은 값입니다. 반영할 필요가 없습니다.</p>
          )}

          {preview.new_count > 0 && (
            <>
              <h3 style={SUB}>새 품목으로 등록 {preview.new_count > preview.new_products.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.new_products.length}개만 표시)</span>}</h3>
              <div className="form-compact field-form" style={{ ...S.formGrid, marginBottom: "var(--space-sm)" }}>
                <label className="field">
                  <span className="field-label">기본 공급업체 *</span>
                  <select value={supplier} disabled={busy} onChange={(e) => setSupplier(e.target.value)} aria-invalid={needsSupplier}>
                    <option value="">공급업체 선택</option>
                    {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </label>
              </div>
              <div style={S.tableBox}>
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th style={S.num}>파일 줄</th><th>SKU</th><th>품목명</th><th>단위</th><th style={S.num}>구매단가</th><th style={S.num}>안전재고</th><th>발주단위</th></tr></thead>
                  <tbody>
                    {preview.new_products.map((p) => (
                      <tr key={p.sku} style={S.row}>
                        <td style={S.num}>{p.row}</td><td>{p.sku}</td><td>{p.name}</td><td>{p.unit}</td>
                        <td style={S.num}>{p.unit_cost.toLocaleString()}</td><td style={S.num}>{p.safety_stock.toLocaleString()}</td>
                        <td>{p.units_per_box ? `${p.order_unit} (1${p.order_unit} = ${p.units_per_box.toLocaleString()}${p.unit})` : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {preview.update_count > 0 && (
            <>
              <h3 style={SUB}>기존 품목 수정 {preview.update_count > preview.updates.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.updates.length}개만 표시)</span>}</h3>
              <div style={S.tableBox}>
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th style={S.num}>파일 줄</th><th>SKU</th><th>품목명</th><th>바뀌는 값 (이전 → 새 값)</th></tr></thead>
                  <tbody>
                    {preview.updates.map((u) => (
                      <tr key={u.sku} style={S.row}>
                        <td style={S.num}>{u.row}</td><td>{u.sku}</td><td>{u.name}</td>
                        <td>{u.changes.map((c) => <div key={c.field}>{c.label}: {shown(c.old)} → {shown(c.new)}</div>)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {preview.problem_count > 0 && (
            <>
              <h3 style={{ ...SUB, color: "var(--color-destructive)" }}>문제 행 {preview.problem_count}건 {preview.problem_count > preview.problems.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.problems.length}건만 표시)</span>}</h3>
              <div style={S.tableBox}>
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th style={S.num}>파일 줄</th><th>SKU</th><th>사유</th></tr></thead>
                  <tbody>
                    {preview.problems.map((p) => (
                      <tr key={p.row} style={S.row}><td style={S.num}>{p.row}</td><td>{p.sku ?? "-"}</td><td>{p.message}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <div style={ACTIONS}>
            {preview.problem_count > 0 && hasWork && (
              <label style={CHECK}>
                <input type="checkbox" checked={exclude} disabled={busy} onChange={(e) => setExclude(e.target.checked)} />
                문제 행 {preview.problem_count}건 제외하고 반영
              </label>
            )}
            <button type="button" className="primary-action" disabled={busy || !canCommit} aria-describedby={blockReason ? "commit-block-reason" : undefined} onClick={() => void commit()}>
              {busy ? "반영 중…" : hasWork ? commitLabel : "반영할 행 없음"}
            </button>
            <InfoTip label="반영 전에 알아 둘 점" detail="품목은 삭제하지 않고 비활성으로 바꿉니다. 이 가져오기는 재고를 바꾸지 않습니다." />
            {blockReason && <span id="commit-block-reason" style={S.hint}>{blockReason}</span>}
          </div>
        </div>
      )}

      {done && (
        <div style={S.sectionCard}>
          <p style={{ ...S.ok, marginTop: 0 }} role="status">
            신규 {done.created_count.toLocaleString()}개를 등록하고 기존 {done.updated_count.toLocaleString()}개를 수정했습니다.
            {done.unchanged_count > 0 && ` 변경 없음 ${done.unchanged_count}개.`}
            {done.problem_count > 0 && ` 문제 행 ${done.problem_count}건은 제외했습니다.`}
          </p>
          {done.preview_changed && done.message && <p role="alert" style={S.error}><strong>확인 필요</strong> {done.message}</p>}
          <button type="button" onClick={() => { reset(null); setInputKey((k) => k + 1); }}>다른 파일 올리기</button>
        </div>
      )}

      <ErrorText error={error} />
    </section>
  );
}

// 카드 안 간격: 같은 묶음은 좁게, 묶음 사이는 넓게
const BLOCK = { marginTop: "var(--space-md)" } as const;
const SUB = { margin: "var(--space-lg) 0 var(--space-sm)", fontSize: "var(--text-base)" } as const; // 카드 안 소제목
const ACTIONS = { display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "var(--space-sm) var(--space-md)", marginTop: "var(--space-lg)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--color-border)" } as const;
const CHECK = { display: "inline-flex", alignItems: "center", gap: "var(--space-xs)", minHeight: "var(--control-min)" } as const;
