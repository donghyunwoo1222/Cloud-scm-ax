"use client"; // 파일 선택·열 지정 등 브라우저에서 동작하는 화면

import { useRef, useState } from "react";
import { api, ApiError } from "../../lib/api"; // 서버 호출
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { S } from "../../lib/styles"; // 공통 스타일

// 판매 가져오기 (#154, 주소 /sales-import): 파일 → 열 지정 → 미리보기 → 반영.
// 서버는 파일을 기억하지 않으므로 이 화면이 File 객체를 들고 있다가 미리보기·반영 때마다 다시 보낸다.

type Suggested = Record<"product_col" | "quantity_col" | "date_col" | "ref_col" | "status_col" | "option_col", number | null>;
type Inspect = { headers: string[]; row_count: number; suggested: Suggested; status_values: { value: string; count: number }[] | null };
type Problem = { row: number; reason: string; message: string; sku: string | null };
type Preview = {
  total_rows: number; apply_count: number; skipped_count: number; skipped: { reason: string; message: string; count: number }[];
  date_from: string | null; date_to: string | null; total_quantity: number; problem_count: number; problems: Problem[];
  warnings: { sku: string; message: string }[];
};
type Done = { imported_count: number; skipped_count: number; problem_count: number; total_quantity: number; date_from: string; date_to: string };

const CHANNELS = [["SMARTSTORE", "스마트스토어"], ["OWN_MALL", "자사몰"], ["OTHER", "기타"]] as const; // 판매 채널 (출고 등록과 같은 값)
const NONE = ""; // 선택 안 함

export default function Page() {
  const [file, setFile] = useState<File | null>(null);
  const [info, setInfo] = useState<Inspect | null>(null); // 1단계 결과
  const [cols, setCols] = useState({ product: NONE, quantity: NONE, date: NONE, ref: NONE, status: NONE, option: NONE }); // 열 번호(글자) 또는 NONE
  const [statuses, setStatuses] = useState<string[]>([]); // 반영할 상태 값
  const [channel, setChannel] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [exclude, setExclude] = useState(false); // "문제 행 제외하고 반영"
  const [done, setDone] = useState<Done | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [inputKey, setInputKey] = useState(0); // 바꾸면 파일 입력칸을 새로 그려 선택한 파일 이름을 지운다
  const sending = useRef(false); // 더블클릭 방지 (상태값은 다음 그리기 뒤에야 바뀌므로 ref 도 함께 쓴다)

  // 서버 호출 한 번을 감싼다: 중복 제출 방지 + 오류 보관
  async function run(job: () => Promise<void>) {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError(null);
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
    product_col: num(cols.product), quantity_col: num(cols.quantity), date_col: num(cols.date), ref_col: num(cols.ref),
    status_col: num(cols.status), statuses: cols.status === NONE ? null : statuses, option_col: num(cols.option),
    sales_channel: channel || null, exclude_problems: excludeProblems,
  });
  const columnsReady = [cols.product, cols.quantity, cols.date, cols.ref].every((v) => v !== NONE);

  function reset(next: File | null) {
    setFile(next); setInfo(null); setPreview(null); setDone(null); setError(null); setStatuses([]); setExclude(false);
    setCols({ product: NONE, quantity: NONE, date: NONE, ref: NONE, status: NONE, option: NONE });
  }

  // 1단계: 파일을 올려 머리글을 읽고 비슷한 열을 미리 고른다
  const inspect = (f: File) => run(async () => {
    reset(f);
    const data = await api<Inspect>("/sales-imports/inspect", { method: "POST", body: form(undefined, f) });
    setInfo(data);
    const s = data.suggested;
    const str = (n: number | null) => (n === null ? NONE : String(n));
    setCols({ product: str(s.product_col), quantity: str(s.quantity_col), date: str(s.date_col), ref: str(s.ref_col), status: NONE, option: str(s.option_col) });
  });

  // 상태 열을 고르면 그 열의 값 목록을 서버에서 받는다 (다른 열 값은 읽지 않는다)
  const pickStatus = (value: string) => run(async () => {
    setCols((c) => ({ ...c, status: value })); setPreview(null); setStatuses([]);
    if (value === NONE) { setInfo((i) => i && { ...i, status_values: null }); return; }
    const data = await api<Inspect>("/sales-imports/inspect", { method: "POST", body: form({ status_col: value }) });
    setInfo((i) => i && { ...i, status_values: data.status_values });
  });

  const runPreview = () => run(async () => {
    setExclude(false);
    setPreview(await api<Preview>("/sales-imports/preview", { method: "POST", body: form({ options: options(false) }) }));
  });

  const commit = () => run(async () => {
    setDone(await api<Done>("/sales-imports", { method: "POST", body: form({ options: options(exclude) }) }));
    setPreview(null);
  });

  const canCommit = preview && preview.apply_count > 0 && channel && (preview.problem_count === 0 || exclude);
  const header = (n: number) => info?.headers[n] || `(${n + 1}번째 열)`;
  // 컴포넌트가 아니라 함수로 부른다: 컴포넌트로 만들면 그릴 때마다 새로 만들어져 선택 상자가 닫힌다
  const colSelect = (label: string, k: keyof typeof cols, optional = false) => (
    <label className="field" key={k}>
      <span className="field-label">{label}{optional ? "" : " *"}</span>
      <select value={cols[k]} disabled={busy}
        onChange={(e) => { if (k === "status") void pickStatus(e.target.value); else { setCols({ ...cols, [k]: e.target.value }); setPreview(null); } }}>
        <option value={NONE}>{optional ? "사용 안 함" : "열 선택"}</option>
        {info?.headers.map((h, i) => <option key={i} value={i}>{h || `(${i + 1}번째 열)`}</option>)}
      </select>
    </label>
  );

  return (
    <section>
      <h1>판매 가져오기</h1>
      <p style={S.hint}>
        쇼핑몰에서 내려받은 주문 파일(.csv, .xlsx, 5MB·5,000행 이하)을 올리면 판매 출고로 기록합니다. 파일은 저장하지 않고,
        수취인·주소·송장 열은 읽지 않습니다. 열 지정은 저장되지 않으니 올릴 때마다 확인해 주세요.
      </p>

      <div style={S.card}>
        <label className="field">
          <span className="field-label">1. 주문 파일</span>
          <input key={inputKey} type="file" accept=".csv,.xlsx" disabled={busy}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) void inspect(f); else reset(null); }} />
        </label>
        {info && <p style={S.hint}>{file?.name} · 데이터 {info.row_count.toLocaleString()}행</p>}
      </div>

      {info && !done && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 열 지정</h2>
          <p style={S.hint}>머리글이 비슷한 열은 미리 골라 두었습니다. 맞는지 확인하세요. 날짜 열의 값이 그대로 출고일이 됩니다.</p>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("상품 코드(SKU)", "product")}
            {colSelect("수량", "quantity")}
            {colSelect("날짜(주문일·발송일)", "date")}
            {colSelect("고유 주문번호", "ref")}
            {colSelect("상태 (선택)", "status", true)}
            {colSelect("옵션 (선택, 섞임 경고용)", "option", true)}
            <label className="field">
              <span className="field-label">판매 채널 *</span>
              <select value={channel} disabled={busy} onChange={(e) => setChannel(e.target.value)}>
                <option value="">채널 선택</option>
                {CHANNELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
          </div>

          {cols.status !== NONE && info.status_values && (
            <fieldset style={{ marginTop: "var(--space-md)" }}>
              <legend>반영할 상태 ({header(Number(cols.status))})</legend>
              <p style={S.hint}>출고가 끝난 값(예: 배송 중, 배송완료)만 고르세요. 고르지 않은 값은 건너뜁니다. 상태는 저장하지 않습니다.</p>
              {info.status_values.map((v) => (
                <label key={v.value} style={{ display: "block", minHeight: "var(--control-min)" }}>
                  <input type="checkbox" checked={statuses.includes(v.value)} disabled={busy}
                    onChange={(e) => { setStatuses(e.target.checked ? [...statuses, v.value] : statuses.filter((x) => x !== v.value)); setPreview(null); }} />
                  {" "}{v.value || "(빈 값)"} <span style={S.hint}>{v.count}건</span>
                </label>
              ))}
            </fieldset>
          )}

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
            <strong>반영 {preview.apply_count.toLocaleString()}건</strong> · 총 수량 {preview.total_quantity.toLocaleString()}
            {preview.date_from && <> · 날짜 {preview.date_from} ~ {preview.date_to}</>}
          </p>
          {preview.skipped.length > 0 && (
            <p style={S.hint}>건너뜀 {preview.skipped_count}건: {preview.skipped.map((s) => `${s.message} ${s.count}건`).join(", ")}</p>
          )}
          {preview.warnings.map((w) => <p key={w.sku} role="alert" style={S.error}>⚠ {w.message} 색상·사이즈별로 재고를 따로 세려면 SKU를 나눠 등록하세요.</p>)}

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

          {!channel && <p style={S.hint}>판매 채널을 고르면 반영할 수 있습니다.</p>}
          <button type="button" disabled={busy || !canCommit} onClick={() => void commit()}>
            {busy ? "반영 중…" : `${preview.apply_count.toLocaleString()}건 반영`}
          </button>
          <p style={S.hint}>반영한 이력은 되돌릴 수 없습니다(잘못된 건은 재고 현황에서 정정). 위 요약을 확인한 뒤 누르세요.</p>
        </div>
      )}

      {done && (
        <div style={S.sectionCard}>
          <p style={S.ok} role="status">
            {done.imported_count.toLocaleString()}건을 판매 출고로 기록했습니다 (총 수량 {done.total_quantity.toLocaleString()}, {done.date_from} ~ {done.date_to}).
            {done.skipped_count > 0 && ` 건너뜀 ${done.skipped_count}건.`}
            {done.problem_count > 0 && ` 문제 행 ${done.problem_count}건은 제외했습니다.`}
          </p>
          <button type="button" onClick={() => { reset(null); setInputKey((k) => k + 1); }}>다른 파일 올리기</button>
        </div>
      )}

      <ErrorText error={error} />
      {error instanceof ApiError && error.code === "DUPLICATE_REF" && <p style={S.hint}>미리보기부터 다시 진행해 주세요.</p>}
    </section>
  );
}
