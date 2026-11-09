"use client"; // 파일 선택·열 지정 등 브라우저에서 동작하는 화면

import { useEffect, useRef, useState } from "react";
import { api, apiList } from "../../lib/api"; // 서버 호출
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { S } from "../../lib/styles"; // 공통 스타일

// 품목·입고 가져오기 (#155, 주소 /receipt-import): 판매 가져오기와 같은 흐름(파일 → 열 지정 → 미리보기 → 반영).
// 입고 목록 파일 하나로 없는 SKU 는 새 품목으로 등록하고 입고까지 한 번에 한다. 수량 열을 안 고르면 품목만 등록한다.

type ColKey = "product" | "quantity" | "date" | "ref" | "name" | "unit" | "cost" | "safety" | "supplier";
type Inspect = { headers: string[]; row_count: number; suggested: Record<`${ColKey}_col`, number | null> };
type NewProduct = { row: number; sku: string; name: string; unit: string; unit_cost: number; safety_stock: number };
type Problem = { row: number; reason: string; message: string; sku: string | null };
type Preview = {
  total_rows: number; apply_count: number; new_product_count: number; new_products: NewProduct[];
  skipped_count: number; skipped: { reason: string; message: string; count: number }[];
  date_from: string | null; date_to: string | null; total_quantity: number; problem_count: number; problems: Problem[];
  warnings: { sku: string; date: string; message: string }[]; // 같은 날·같은 품목 입고가 이미 있음 (막지 않고 알림)
};
type Done = { created_product_count: number; imported_count: number; total_quantity: number; skipped_count: number; problem_count: number };

const NONE = ""; // 선택 안 함
const KEYS: ColKey[] = ["product", "quantity", "date", "ref", "name", "unit", "cost", "safety", "supplier"];
const EMPTY = Object.fromEntries(KEYS.map((k) => [k, NONE])) as Record<ColKey, string>;

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
  const sending = useRef(false); // 더블클릭 방지

  // shortcut: 공급업체는 100개까지만 불러온다 (다른 선택 상자와 같은 한계), 넘으면 검색형으로 바꾼다
  useEffect(() => { apiList<{ id: number; name: string }>("/suppliers?page_size=100").then((r) => setSuppliers(r.data)).catch(setError); }, []);

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
  const options = (excludeProblems: boolean) => JSON.stringify({
    ...Object.fromEntries(KEYS.map((k) => [`${k}_col`, num(cols[k])])),
    default_supplier_id: supplier ? Number(supplier) : null, exclude_problems: excludeProblems,
  });
  const receipts = cols.quantity !== NONE; // 수량 열을 골랐으면 입고 모드
  const columnsReady = cols.product !== NONE && (!receipts || cols.date !== NONE);

  function reset(next: File | null) {
    setFile(next); setInfo(null); setPreview(null); setDone(null); setError(null); setExclude(false); setCols(EMPTY);
  }

  const inspect = (f: File) => run(async () => {
    reset(f);
    const data = await api<Inspect>("/receipt-imports/inspect", { method: "POST", body: form(undefined, f) });
    setInfo(data);
    setCols(Object.fromEntries(KEYS.map((k) => [k, data.suggested[`${k}_col`] === null ? NONE : String(data.suggested[`${k}_col`])])) as Record<ColKey, string>);
  });

  const runPreview = () => run(async () => {
    setExclude(false);
    setPreview(await api<Preview>("/receipt-imports/preview", { method: "POST", body: form({ options: options(false) }) }));
  });

  const commit = () => run(async () => {
    setDone(await api<Done>("/receipt-imports", { method: "POST", body: form({ options: options(exclude) }) }));
    setPreview(null);
  });

  const needsSupplier = (preview?.new_product_count ?? 0) > 0 && !supplier;
  const hasWork = preview && (preview.apply_count > 0 || preview.new_product_count > 0);
  const canCommit = hasWork && !needsSupplier && (preview.problem_count === 0 || exclude);
  const colSelect = (label: string, k: ColKey, required = false) => (
    <label className="field" key={k}>
      <span className="field-label">{label}{required ? " *" : ""}</span>
      <select value={cols[k]} disabled={busy} onChange={(e) => { setCols({ ...cols, [k]: e.target.value }); setPreview(null); }}>
        <option value={NONE}>{required ? "열 선택" : "사용 안 함"}</option>
        {info?.headers.map((h, i) => <option key={i} value={i}>{h || `(${i + 1}번째 열)`}</option>)}
      </select>
    </label>
  );
  const commitLabel = [preview?.new_product_count ? `새 품목 ${preview.new_product_count}개 등록` : "", preview?.apply_count ? `입고 ${preview.apply_count}건` : ""]
    .filter(Boolean).join(" + ");

  return (
    <section>
      <h1>품목·입고 가져오기</h1>
      <p style={S.hint}>
        공급업체 입고 목록이나 품목 목록 파일(.csv, .xlsx, 5MB·5,000행 이하)을 올리면, 없는 상품 코드는 새 품목으로 등록하고
        입고(발주 없는 직접 입고)까지 한 번에 기록합니다. 수량 열을 고르지 않으면 품목만 등록합니다. 기존 품목 정보는 바꾸지 않습니다. 새 품목은 모두 아래에서 고른 공급업체 하나로 등록되니, 공급업체가 여러 곳이면 파일을 나눠 올려 주세요.
      </p>

      <div style={S.card}>
        <label className="field">
          <span className="field-label">1. 파일</span>
          <input key={inputKey} type="file" accept=".csv,.xlsx" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void inspect(f); else reset(null); }} />
        </label>
        {info && <p style={S.hint}>{file?.name} · 데이터 {info.row_count.toLocaleString()}행</p>}
      </div>

      {info && !done && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 열 지정</h2>
          <p style={S.hint}>머리글이 비슷한 열은 미리 골라 두었습니다. 고유 번호 열이 없으면 날짜·상품 코드·수량으로 같은 입고를 알아봅니다.</p>
          <h3>입고</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("상품 코드(SKU)", "product", true)}
            {colSelect("수량 (없으면 품목만 등록)", "quantity")}
            {receipts && colSelect("입고일", "date", true)}
            {receipts && colSelect("고유 번호 (선택)", "ref")}
          </div>
          <h3>새 품목 정보 (없는 상품 코드만 사용)</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("품목명", "name")}
            {colSelect("단위", "unit")}
            {colSelect("단가(원)", "cost")}
            {colSelect("안전재고 (비면 0)", "safety")}
            {colSelect("공급업체 열 (선택, 섞임 확인용)", "supplier")}
            <label className="field">
              <span className="field-label">기본 공급업체</span>
              <select value={supplier} disabled={busy} onChange={(e) => { setSupplier(e.target.value); setPreview(null); }}>
                <option value="">공급업체 선택</option>
                {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </label>
          </div>
          <div style={{ marginTop: "var(--space-md)" }}>
            <button type="button" disabled={busy || !columnsReady} onClick={() => void runPreview()}>
              {busy ? "확인 중…" : "미리보기"}
            </button>
          </div>
        </div>
      )}

      {preview && !done && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>3. 미리보기</h2>
          <p>
            <strong>새 품목 {preview.new_product_count.toLocaleString()}개 등록{receipts && ` + 입고 ${preview.apply_count.toLocaleString()}건`}</strong>
            {receipts && <> · 총 수량 {preview.total_quantity.toLocaleString()}</>}
            {preview.date_from && <> · 날짜 {preview.date_from} ~ {preview.date_to}</>}
          </p>
          {preview.skipped.length > 0 && (
            <p style={S.hint}>건너뜀 {preview.skipped_count}건: {preview.skipped.map((s) => `${s.message} ${s.count}건`).join(", ")}</p>
          )}
          {(() => { // 넣을 줄이 없고 이미 반영된 줄만 있으면, 버튼의 "반영할 행 없음"만으로는 이유가 안 보여 크게 알린다
            const already = preview.skipped.find((s) => s.reason === "ALREADY_IMPORTED")?.count ?? 0;
            return !hasWork && already > 0 && (
              <p role="status" style={S.ok}>
                이 파일은 이미 모두 반영되었습니다 ({already.toLocaleString()}건). 다시 반영할 필요가 없습니다.
                {preview.problem_count > 0 && ` 문제 행 ${preview.problem_count}건은 파일에서 고친 뒤 다시 올리면 그 줄만 반영됩니다.`}
              </p>
            );
          })()}

          {preview.warnings.map((w) => <p key={`${w.sku}-${w.date}`} role="alert" style={S.error}>⚠ {w.message}</p>)}

          {preview.new_product_count > 0 && (
            <>
              <h3>새 품목으로 등록{preview.new_product_count > preview.new_products.length && ` (앞 ${preview.new_products.length}개만 표시)`}</h3>
              <div style={S.tableBox}>
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th>파일 줄</th><th>상품 코드</th><th>품목명</th><th>단위</th><th>단가</th><th>안전재고</th></tr></thead>
                  <tbody>
                    {preview.new_products.map((p) => (
                      <tr key={p.sku} style={S.row}>
                        <td style={S.num}>{p.row}</td><td>{p.sku}</td><td>{p.name}</td><td>{p.unit}</td>
                        <td style={S.num}>{p.unit_cost.toLocaleString()}</td><td style={S.num}>{p.safety_stock.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {needsSupplier && <p role="alert" style={S.error}>새 품목의 기본 공급업체를 위에서 골라 주세요.</p>}
            </>
          )}

          {preview.problem_count > 0 && (
            <>
              <p role="alert" style={S.error}>문제 행 {preview.problem_count}건{preview.problem_count > preview.problems.length && ` (앞 ${preview.problems.length}건만 표시)`}</p>
              <div style={S.tableBox}>
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th>파일 줄</th><th>상품 코드</th><th>사유</th></tr></thead>
                  <tbody>
                    {preview.problems.map((p) => (
                      <tr key={p.row} style={S.row}><td style={S.num}>{p.row}</td><td>{p.sku ?? "-"}</td><td>{p.message}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <label style={{ display: "block", marginTop: "var(--space-md)", minHeight: "var(--control-min)" }}>
                <input type="checkbox" checked={exclude} disabled={busy} onChange={(e) => setExclude(e.target.checked)} />
                {" "}문제 행 {preview.problem_count}건 제외하고 반영
              </label>
            </>
          )}

          <button type="button" disabled={busy || !canCommit} onClick={() => void commit()}>
            {busy ? "반영 중…" : hasWork ? commitLabel : "반영할 행 없음"}
          </button>
          <p style={S.hint}>입고 이력은 되돌릴 수 없고(잘못된 건은 재고 현황에서 정정), 품목은 삭제 대신 비활성으로 바꿉니다. 위 요약을 확인한 뒤 누르세요.</p>
        </div>
      )}

      {done && (
        <div style={S.sectionCard}>
          <p style={S.ok} role="status">
            새 품목 {done.created_product_count.toLocaleString()}개를 등록하고 입고 {done.imported_count.toLocaleString()}건(총 수량 {done.total_quantity.toLocaleString()})을 기록했습니다.
            {done.skipped_count > 0 && ` 건너뜀 ${done.skipped_count}건.`}
            {done.problem_count > 0 && ` 문제 행 ${done.problem_count}건은 제외했습니다.`}
          </p>
          <button type="button" onClick={() => { reset(null); setInputKey((k) => k + 1); }}>다른 파일 올리기</button>
        </div>
      )}

      <ErrorText error={error} />
    </section>
  );
}
