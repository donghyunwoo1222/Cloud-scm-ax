"use client"; // 파일 선택·열 지정 등 브라우저에서 동작하는 화면

import { useEffect, useRef, useState } from "react";
import { api, apiListAll } from "../../lib/api"; // 서버 호출
import { fetchSuggest, NO_AI_NOTICE, NO_AI_REASONS, ReadingConfirm, type Suggest } from "../../lib/import-suggest"; // "이렇게 읽었어요" (#193)
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { S } from "../../lib/styles"; // 공통 스타일
import { InfoTip } from "../../lib/tip"; // 보조 설명 말풍선

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
type Key = `${ColKey}_col`; // /suggest 의 칸 이름 (inspect 의 suggested 키와 같다)
const FIELDS: readonly (readonly [Key, string])[] = [ // 확인 화면의 칸 순서와 이름 (열 지정 화면의 이름과 같다)
  ["product_col", "상품 코드(SKU)"], ["quantity_col", "수량"], ["date_col", "입고일"], ["ref_col", "고유 번호"],
  ["name_col", "품목명"], ["unit_col", "단위"], ["cost_col", "단가(원)"], ["safety_col", "안전재고"], ["supplier_col", "공급업체"],
];
const REQUIRED_KEYS: Key[] = ["product_col"]; // 입고 가져오기의 필수 열은 상품 코드 하나 (수량이 있으면 날짜도 필요하지만 서버가 검사해서 보낸다)
const SHOW_KEYS: Key[] = ["product_col", "quantity_col"]; // 짝이 없어도 보여 줄 칸: 수량을 못 읽으면 "품목만 등록"으로 조용히 넘어가므로 경고한다
// 열 번호 → 선택 상자 값 (없으면 NONE)
const toCols = (m: Record<Key, number | null>) => Object.fromEntries(KEYS.map((k) => [k, m[`${k}_col`] === null ? NONE : String(m[`${k}_col`])])) as Record<ColKey, string>;

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
  const [reading, setReading] = useState(false); // 파일을 읽고 /suggest 답을 기다리는 중
  const [suggestion, setSuggestion] = useState<Suggest<Key> | null>(null); // llm 이 읽은 결과 → "이렇게 읽었어요" 확인 화면
  const [notice, setNotice] = useState<string | null>(null); // 열 지정 화면 위 한 줄 안내
  const reqId = useRef(0); // 파일 선택·직접 지정마다 올린다: 늦게 도착한 /suggest 결과가 새 화면을 덮지 못하게 비교한다
  const [inputKey, setInputKey] = useState(0);
  const previewHeading = useRef<HTMLHeadingElement>(null); // 미리보기 결과가 화면 아래에 생기므로 포커스를 옮겨 알린다
  useEffect(() => {
    if (!preview || !previewHeading.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; // 움직임 줄이기를 켰으면 바로 이동
    previewHeading.current.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    previewHeading.current.focus({ preventScroll: true });
  }, [preview]);
  const sending = useRef(false); // 더블클릭 방지

  // 공급업체를 100개씩 끝까지 읽는다 (1,000곳 이상이면 검색형으로 바꾸는 것은 후속)
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
  const options = (excludeProblems: boolean, c = cols) => JSON.stringify({
    ...Object.fromEntries(KEYS.map((k) => [`${k}_col`, num(c[k])])),
    default_supplier_id: supplier ? Number(supplier) : null, exclude_problems: excludeProblems,
  });
  const receipts = cols.quantity !== NONE; // 수량 열을 골랐으면 입고 모드
  const [missing, setMissing] = useState<string[]>([]); // 미리보기를 눌렀을 때 비어 있던 필수 칸
  const requiredCols: [ColKey, string][] = [["product", "상품 코드(SKU)"], ...(receipts ? [["date", "입고일"] as [ColKey, string]] : [])]; // 수량 열을 골랐으면 입고일도 필수
  // 필수 칸이 비었으면 버튼을 막는 대신, 첫 빈 칸으로 포커스를 옮기고 빨간 안내를 보여준다
  const tryPreview = () => {
    const miss = requiredCols.filter(([k]) => cols[k] === NONE);
    setMissing(miss.map(([k]) => k));
    if (miss.length) document.getElementById(`col-${miss[0][0]}`)?.focus();
    else void runPreview();
  };
  const shownMissing = requiredCols.filter(([k]) => missing.includes(k) && cols[k] === NONE); // 채우면 안내가 사라진다

  function reset(next: File | null) {
    reqId.current++; // 이전 파일의 늦은 /suggest 결과를 버리게 한다
    setMissing([]);
    setFile(next); setInfo(null); setPreview(null); setDone(null); setError(null); setExclude(false); setCols(EMPTY);
    setReading(false); setSuggestion(null); setNotice(null);
  }

  // 1단계: 파일을 올려 머리글을 읽고 비슷한 열을 미리 고른다. 그다음 /suggest 를 이 파일에 한 번만 부른다
  const inspect = (f: File) => run(async () => {
    reset(f);
    const id = reqId.current;
    setReading(true);
    let data: Inspect;
    try { data = await api<Inspect>("/receipt-imports/inspect", { method: "POST", body: form(undefined, f) }); }
    catch (e) { if (id === reqId.current) setReading(false); throw e; } // inspect 오류만 오류로 보여준다
    if (id !== reqId.current) return;
    setInfo(data);
    setCols(toCols(data.suggested));
    void readColumns(f, id); // run 밖에서 기다린다: 기다리는 동안 "직접 지정"·다른 파일 선택이 막히지 않게
  });

  // /suggest 결과에 따라 화면을 정한다. 입고에는 템플릿이 없어 template 은 오지 않는다 (오면 기존 화면)
  async function readColumns(f: File, id: number) {
    const s = await fetchSuggest<Key>("/receipt-imports/suggest", f);
    if (id !== reqId.current) return; // 그 사이 다른 파일을 골랐거나 "직접 지정"을 눌렀다
    setReading(false);
    if (s?.source === "llm" && s.mapping && s.samples && s.confidence) { setSuggestion(s); return; }
    if (s?.source === "rules" && s.reason && NO_AI_REASONS.includes(s.reason)) setNotice(NO_AI_NOTICE);
  }

  // "기다리지 않고 직접 지정": 이미 채워 둔 inspect 의 suggested 로 열 지정 화면을 바로 연다. 늦게 오는 /suggest 결과는 id 가 달라 버려진다
  const skipWaiting = () => { reqId.current++; setReading(false); };

  // 확인 화면 "맞아요": 읽은 열로 바로 미리보기 (상품 코드가 있을 때만 버튼이 켜진다)
  const confirmReading = () => {
    if (!suggestion?.mapping) return;
    const c = toCols(suggestion.mapping);
    setCols(c); setSuggestion(null);
    void runPreview(c);
  };

  // c: "맞아요" 직후에는 아직 반영 안 된 새 열 값을 직접 넘긴다
  const runPreview = (c = cols) => run(async () => {
    setExclude(false);
    setPreview(await api<Preview>("/receipt-imports/preview", { method: "POST", body: form({ options: options(false, c) }) }));
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
      <select id={`col-${k}`} aria-invalid={shownMissing.some(([m]) => m === k)} value={cols[k]} disabled={busy} onChange={(e) => { setCols({ ...cols, [k]: e.target.value }); setPreview(null); }}>
        <option value={NONE}>{required ? "열 선택" : "사용 안 함"}</option>
        {info?.headers.map((h, i) => <option key={i} value={i}>{h || `(${i + 1}번째 열)`}</option>)}
      </select>
    </label>
  );
  const commitLabel = [preview?.new_product_count ? `새 품목 ${preview.new_product_count}개 등록` : "", preview?.apply_count ? `입고 ${preview.apply_count}건` : ""]
    .filter(Boolean).join(" + ");
  // 반영 버튼이 막힌 이유를 버튼 옆에 적는다 (막힌 버튼만 보면 무엇을 해야 하는지 모른다)
  const blockReason = !preview || !hasWork ? null
    : needsSupplier ? "새 품목의 기본 공급업체를 고르면 반영할 수 있습니다"
    : preview.problem_count > 0 && !exclude ? "문제 행을 파일에서 고치거나, 제외하고 반영을 체크하세요" : null;

  return (
    <section>
      <h1>품목·입고 가져오기</h1>
      <p style={S.hint}>
        입고 목록 파일 하나로 새 품목 등록과 입고를 한 번에 합니다{" "}
        <InfoTip detail="없는 상품 코드는 새 품목으로 등록하고 직접 입고(발주 없음)까지 기록합니다. 수량 열을 고르지 않으면 품목만 등록합니다. 기존 품목 정보는 바꾸지 않습니다. 새 품목은 모두 고른 공급업체 하나로 등록되니, 공급업체가 여러 곳이면 파일을 나눠 올려 주세요. 파일은 .csv·.xlsx, 5MB·5,000행 이하이고 저장하지 않습니다." />
      </p>

      <div style={S.sectionCard}>
        <h2 style={{ marginTop: 0 }}>1. 파일 올리기</h2>
        <input key={inputKey} type="file" accept=".csv,.xlsx" disabled={busy} aria-label="입고·품목 파일"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void inspect(f); else reset(null); }} />
        {info && <p style={{ ...S.hint, marginBottom: 0 }}>{file?.name} · 데이터 {info.row_count.toLocaleString()}행</p>}
      </div>

      {reading && (
        <p role="status" style={S.hint}>
          열을 읽는 중…{" "}
          {info && <button type="button" onClick={skipWaiting}>기다리지 않고 직접 지정</button>}
        </p>
      )}

      {info && !done && !reading && suggestion?.mapping && suggestion.samples && suggestion.confidence && (
        <ReadingConfirm fields={FIELDS} mapping={suggestion.mapping} samples={suggestion.samples} confidence={suggestion.confidence}
          header={(n) => info.headers[n] || `(${n + 1}번째 열)`} required={REQUIRED_KEYS} show={SHOW_KEYS} busy={busy}
          warn={{ quantity_col: "읽지 못함 (이대로면 품목만 등록하고 입고는 기록하지 않아요)" }}
          onYes={confirmReading} onNo={() => setSuggestion(null)} />
      )}

      {info && !done && !reading && !suggestion && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 열 지정</h2>
          {notice && <p role="status" style={S.hint}>{notice}</p>}
          <p style={S.hint}>
            머리글이 비슷한 열은 미리 골라 두었습니다. 맞는지 확인하세요{" "}
            <InfoTip detail="고유 번호 열이 없으면 날짜·상품 코드·수량으로 같은 입고를 알아봅니다. 열 지정은 저장되지 않습니다." />
          </p>
          <h3 style={SUB}>입고</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("상품 코드(SKU)", "product", true)}
            {colSelect("수량 (없으면 품목만 등록)", "quantity")}
            {receipts && colSelect("입고일", "date", true)}
            {receipts && colSelect("고유 번호 (선택)", "ref")}
          </div>
          <h3 style={SUB}>새 품목 정보 <span style={{ ...S.hint, fontWeight: 400 }}>(없는 상품 코드에만 사용)</span></h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("품목명", "name")}
            {colSelect("단위", "unit")}
            {colSelect("단가(원)", "cost")}
            {colSelect("안전재고 (선택, 비면 0)", "safety")}
            {colSelect("공급업체 (선택, 섞임 확인용)", "supplier")}
          </div>
          <div style={BLOCK}>
            <button type="button" className="primary-action" disabled={busy} onClick={tryPreview}>
              {busy ? "확인 중…" : "미리보기"}
            </button>
            {shownMissing.length > 0 && <p role="alert" style={{ ...S.error, margin: "var(--space-sm) 0 0" }}>필수 칸을 골라 주세요: {shownMissing.map(([, l]) => l).join(", ")}</p>}
          </div>
        </div>
      )}

      {preview && !done && (
        <div style={S.sectionCard}>
          <h2 ref={previewHeading} tabIndex={-1} style={{ marginTop: 0, outline: "none" }}>3. 미리보기</h2>
          <p style={{ margin: 0, fontVariantNumeric: "tabular-nums" }}>
            <strong>새 품목 {preview.new_product_count.toLocaleString()}개 등록{receipts && ` + 입고 ${preview.apply_count.toLocaleString()}건`}</strong>
            {receipts && <> · 총 수량 {preview.total_quantity.toLocaleString()}</>}
            {preview.date_from && <> · 날짜 {preview.date_from} ~ {preview.date_to}</>}
          </p>
          {preview.skipped.length > 0 && (
            <p style={{ ...S.hint, margin: "var(--space-xs) 0 0" }}>건너뜀 {preview.skipped_count}건: {preview.skipped.map((s) => `${s.message} ${s.count}건`).join(", ")}</p>
          )}
          {(() => { // 넣을 줄이 없고 이미 반영된 줄만 있으면, 버튼의 "반영할 행 없음"만으로는 이유가 안 보여 크게 알린다
            const already = preview.skipped.find((s) => s.reason === "ALREADY_IMPORTED")?.count ?? 0;
            return !hasWork && already > 0 && (
              <p role="status" style={{ ...S.ok, ...BLOCK }}>
                이 파일은 이미 모두 반영되었습니다 ({already.toLocaleString()}건). 다시 반영할 필요가 없습니다.
                {preview.problem_count > 0 && ` 문제 행 ${preview.problem_count}건은 파일에서 고친 뒤 다시 올리면 그 줄만 반영됩니다.`}
              </p>
            );
          })()}

          {preview.warnings.length > 0 && (
            <div role="alert" style={BLOCK}>
              {preview.warnings.map((w) => <p key={`${w.sku}-${w.date}`} style={{ ...S.error, margin: "0 0 var(--space-xs)" }}><strong>확인 필요</strong> {w.message}</p>)}
            </div>
          )}

          {preview.new_product_count > 0 && (
            <>
              <h3 style={SUB}>새 품목으로 등록 {preview.new_product_count > preview.new_products.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.new_products.length}개만 표시)</span>}</h3>
              <div className="form-compact field-form" style={{ ...S.formGrid, marginBottom: "var(--space-sm)" }}>
                <label className="field">
                  <span className="field-label">기본 공급업체 *</span>
                  <select value={supplier} disabled={busy} onChange={(e) => setSupplier(e.target.value)} aria-invalid={needsSupplier}>
                    <option value="">공급업체 선택</option>
                    {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </label>
              </div>
              <div className="table-box">
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th style={S.num}>파일 줄</th><th>상품 코드</th><th>품목명</th><th>단위</th><th style={S.num}>단가</th><th style={S.num}>안전재고</th></tr></thead>
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
            </>
          )}

          {preview.problem_count > 0 && (
            <>
              <h3 style={{ ...SUB, color: "var(--color-destructive)" }}>문제 행 {preview.problem_count}건 {preview.problem_count > preview.problems.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.problems.length}건만 표시)</span>}</h3>
              <div className="table-box">
                <table style={S.table}>
                  <thead><tr style={S.headRow}><th style={S.num}>파일 줄</th><th>상품 코드</th><th>사유</th></tr></thead>
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
            <InfoTip label="반영 전에 알아 둘 점" detail="입고 이력은 되돌릴 수 없습니다(잘못된 건은 재고 현황에서 정정). 품목은 삭제하지 않고 비활성으로 바꿉니다." />
            {blockReason && <span id="commit-block-reason" style={S.hint}>{blockReason}</span>}
          </div>
        </div>
      )}

      {done && (
        <div style={S.sectionCard}>
          <p style={{ ...S.ok, marginTop: 0 }} role="status">
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

// 카드 안 간격: 같은 묶음은 좁게, 묶음 사이는 넓게
const BLOCK = { marginTop: "var(--space-md)" } as const;
const SUB = { margin: "var(--space-lg) 0 var(--space-sm)", fontSize: "var(--text-base)" } as const; // 카드 안 소제목
const ACTIONS = { display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "var(--space-sm) var(--space-md)", marginTop: "var(--space-lg)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--color-border)" } as const; // 반영 줄: 체크·버튼·이유를 한 줄에
const CHECK = { display: "inline-flex", alignItems: "center", gap: "var(--space-xs)", minHeight: "var(--control-min)" } as const;
