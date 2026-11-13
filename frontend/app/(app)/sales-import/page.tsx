"use client"; // 파일 선택·열 지정 등 브라우저에서 동작하는 화면

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../../lib/api"; // 서버 호출
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { S } from "../../lib/styles"; // 공통 스타일
import { InfoTip } from "../../lib/tip"; // 보조 설명 말풍선

// 판매 가져오기 (#154, 주소 /sales-import): 파일 → 열 지정 → 미리보기 → 반영.
// 서버는 파일을 기억하지 않으므로 이 화면이 File 객체를 들고 있다가 미리보기·반영 때마다 다시 보낸다.

type Suggested = Record<"product_col" | "quantity_col" | "date_col" | "ref_col" | "status_col" | "option_col", number | null>;
type Inspect = { headers: string[]; row_count: number; suggested: Suggested; status_values: { value: string; count: number }[] | null };
// /sales-imports/suggest 응답 (#193). rules 면 mapping·confidence·samples 가 null, reason 은 코드 값(화면에 그대로 보이지 않는다)
type Suggest = {
  source: "template" | "llm" | "rules"; reason: string | null; mapping: Suggested | null;
  confidence: Partial<Record<keyof Suggested, "high" | "low">> | null; samples: Partial<Record<keyof Suggested, string[]>> | null;
};
type Problem = { row: number; reason: string; message: string; sku: string | null };
type Preview = {
  total_rows: number; apply_count: number; skipped_count: number; skipped: { reason: string; message: string; count: number }[];
  date_from: string | null; date_to: string | null; total_quantity: number; problem_count: number; problems: Problem[];
  warnings: { sku: string; message: string }[];
};
type Done = { imported_count: number; skipped_count: number; problem_count: number; total_quantity: number; date_from: string; date_to: string };

const CHANNELS = [["SMARTSTORE", "스마트스토어"], ["OWN_MALL", "자사몰"], ["OTHER", "기타"]] as const; // 판매 채널 (출고 등록과 같은 값)
const NONE = ""; // 선택 안 함
const str = (n: number | null) => (n === null ? NONE : String(n)); // 열 번호 → 선택 상자 값
// 확인 화면의 칸 순서와 이름 (필수 4칸 먼저)
const FIELDS = [["product_col", "상품 코드(SKU)"], ["quantity_col", "수량"], ["date_col", "날짜"], ["ref_col", "고유 주문번호"], ["status_col", "상태"], ["option_col", "옵션"]] as const;
const NO_AI_REASONS = ["DAILY_LIMIT", "BUDGET"]; // 한도 초과일 때만 "AI 추천을 쓸 수 없어요" 안내 (꺼짐·장애는 조용히 기존 화면)

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
  const [reading, setReading] = useState(false); // 파일을 읽고 /suggest 답을 기다리는 중
  const [suggestion, setSuggestion] = useState<Suggest | null>(null); // llm 이 읽은 결과 → "이렇게 읽었어요" 확인 화면
  const [notice, setNotice] = useState<string | null>(null); // 열 지정 화면 위 한 줄 안내
  const reqId = useRef(0); // 파일 선택·직접 지정마다 올린다: 늦게 도착한 /suggest 결과가 새 화면을 덮지 못하게 비교한다
  const [inputKey, setInputKey] = useState(0); // 바꾸면 파일 입력칸을 새로 그려 선택한 파일 이름을 지운다
  const previewHeading = useRef<HTMLHeadingElement>(null); // 미리보기 결과가 화면 아래에 생기므로 포커스를 옮겨 알린다
  useEffect(() => {
    if (!preview || !previewHeading.current) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; // 움직임 줄이기를 켰으면 바로 이동
    previewHeading.current.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    previewHeading.current.focus({ preventScroll: true });
  }, [preview]);
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
  const options = (excludeProblems: boolean, c = cols) => JSON.stringify({
    product_col: num(c.product), quantity_col: num(c.quantity), date_col: num(c.date), ref_col: num(c.ref),
    status_col: num(c.status), statuses: c.status === NONE ? null : statuses, option_col: num(c.option),
    sales_channel: channel || null, exclude_problems: excludeProblems,
  });
  const columnsReady = [cols.product, cols.quantity, cols.date, cols.ref].every((v) => v !== NONE);

  function reset(next: File | null) {
    reqId.current++; // 이전 파일의 늦은 /suggest 결과를 버리게 한다
    setFile(next); setInfo(null); setPreview(null); setDone(null); setError(null); setStatuses([]); setExclude(false);
    setReading(false); setSuggestion(null); setNotice(null);
    setCols({ product: NONE, quantity: NONE, date: NONE, ref: NONE, status: NONE, option: NONE });
  }

  // 1단계: 파일을 올려 머리글을 읽고 비슷한 열을 미리 고른다. 그다음 /suggest 를 이 파일에 한 번만 부른다
  const inspect = (f: File) => run(async () => {
    reset(f);
    const id = reqId.current;
    setReading(true);
    let data: Inspect;
    try { data = await api<Inspect>("/sales-imports/inspect", { method: "POST", body: form(undefined, f) }); }
    catch (e) { if (id === reqId.current) setReading(false); throw e; } // inspect 오류만 오류로 보여준다
    if (id !== reqId.current) return;
    setInfo(data);
    const s = data.suggested;
    setCols({ product: str(s.product_col), quantity: str(s.quantity_col), date: str(s.date_col), ref: str(s.ref_col), status: NONE, option: str(s.option_col) });
    void readColumns(f, id); // run 밖에서 기다린다: 기다리는 동안 "직접 지정"·다른 파일 선택이 막히지 않게
  });

  // /suggest 를 부르고 결과에 따라 화면을 정한다. 오류는 모두 삼키고(값은 로그·오류에 남기지 않는다) 기존 열 지정 화면으로 이어간다
  async function readColumns(f: File, id: number) {
    let s: Suggest | null = null;
    try { s = await api<Suggest>("/sales-imports/suggest", { method: "POST", body: form(undefined, f) }); } catch { s = null; }
    if (id !== reqId.current) return; // 그 사이 다른 파일을 골랐거나 "직접 지정"을 눌렀다
    if (s?.source === "llm" && s.mapping && s.samples && s.confidence) { setSuggestion(s); setReading(false); return; }
    if (s?.source === "rules" && s.reason && NO_AI_REASONS.includes(s.reason)) setNotice("오늘은 AI 추천을 쓸 수 없어 기본 추천으로 열었어요.");
    if (s?.source === "template" && s.mapping) { // 열은 서버가 정확히 알지만 상태 값 선택은 남긴다 (status_col 이 없으면 서버가 상태를 거르지 않는다)
      const m = s.mapping;
      try {
        const st = m.status_col === null ? null : await api<Inspect>("/sales-imports/inspect", { method: "POST", body: form({ status_col: String(m.status_col) }, f) });
        if (id !== reqId.current) return;
        setCols({ product: str(m.product_col), quantity: str(m.quantity_col), date: str(m.date_col), ref: str(m.ref_col), status: str(m.status_col), option: str(m.option_col) });
        if (st) setInfo((i) => i && { ...i, status_values: st.status_values });
        setNotice("템플릿과 같은 파일이에요. 반영할 상태만 골라 주세요.");
      } catch (e) { if (id === reqId.current) setError(e); } // 상태 목록 읽기 실패는 /inspect 오류이므로 보여준다 (기존 열 지정 화면으로 이어짐)
    }
    if (id === reqId.current) setReading(false);
  }

  // "기다리지 않고 직접 지정": 이미 채워 둔 inspect 의 suggested 로 열 지정 화면을 바로 연다. 늦게 오는 /suggest 결과는 id 가 달라 버려진다
  const skipWaiting = () => { reqId.current++; setReading(false); };

  // 확인 화면 "맞아요": 열을 채운다. 상태 칸이 있으면 값 목록을 불러와 열 지정 화면에서 사용자가 직접 체크, 없으면 바로 미리보기
  const confirmReading = () => {
    const m = suggestion?.mapping;
    if (!m) return;
    const c = { product: str(m.product_col), quantity: str(m.quantity_col), date: str(m.date_col), ref: str(m.ref_col), status: NONE, option: str(m.option_col) };
    setCols(c); setSuggestion(null);
    if (m.status_col !== null) void pickStatus(String(m.status_col)); // 기존 방식: /inspect 를 status_col 과 함께 (suggest 는 다시 부르지 않는다)
    else void runPreview(c);
  };

  // 상태 열을 고르면 그 열의 값 목록을 서버에서 받는다 (다른 열 값은 읽지 않는다)
  const pickStatus = (value: string) => run(async () => {
    setCols((c) => ({ ...c, status: value })); setPreview(null); setStatuses([]);
    if (value === NONE) { setInfo((i) => i && { ...i, status_values: null }); return; }
    const data = await api<Inspect>("/sales-imports/inspect", { method: "POST", body: form({ status_col: value }) });
    setInfo((i) => i && { ...i, status_values: data.status_values });
  });

  const runPreview = (c = cols) => run(async () => { // c: "맞아요" 직후에는 아직 반영 안 된 새 열 값을 직접 넘긴다
    setExclude(false);
    setPreview(await api<Preview>("/sales-imports/preview", { method: "POST", body: form({ options: options(false, c) }) }));
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

  // 반영 버튼이 막힌 이유를 버튼 옆에 적는다 (막힌 버튼만 보면 무엇을 해야 하는지 모른다)
  const blockReason = !preview || preview.apply_count === 0 ? null
    : !channel ? "판매 채널을 고르면 반영할 수 있습니다"
    : preview.problem_count > 0 && !exclude ? "문제 행을 파일에서 고치거나, 제외하고 반영을 체크하세요" : null;

  return (
    <section>
      <h1>판매 가져오기</h1>
      <p style={S.hint}>
        쇼핑몰 주문 파일을 올려 판매 출고로 한 번에 기록합니다{" "}
        <InfoTip detail="파일은 .csv·.xlsx, 5MB·5,000행 이하이고 저장하지 않습니다. 수취인·주소·송장 열은 읽지 않습니다. 열 지정은 저장되지 않으니 올릴 때마다 확인해 주세요." />
      </p>

      <div style={S.sectionCard}>
        <h2 style={{ marginTop: 0 }}>1. 파일 올리기</h2>
        <input key={inputKey} type="file" accept=".csv,.xlsx" disabled={busy} aria-label="주문 파일"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) void inspect(f); else reset(null); }} />
        <p style={{ ...S.hint, marginBottom: 0 }}>
          {info ? `${file?.name} · 데이터 ${info.row_count.toLocaleString()}행 · ` : ""}템플릿 내려받기:{" "}
          <a href="/api/v1/import-templates/sales.xlsx" download>엑셀</a> · <a href="/api/v1/import-templates/sales.csv" download>CSV</a>
        </p>
      </div>

      {reading && (
        <p role="status" style={S.hint}>
          열을 읽는 중…{" "}
          {info && <button type="button" onClick={skipWaiting}>기다리지 않고 직접 지정</button>}
        </p>
      )}

      {info && !done && !reading && suggestion?.mapping && suggestion.samples && suggestion.confidence && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 이렇게 읽었어요. 맞나요?</h2>
          <p style={S.hint}>파일의 열이 어떤 칸으로 읽혔는지와 그 열의 앞쪽 값을 보여줍니다. 값이 이상하면 &quot;다르게 읽혔어요&quot;를 누르세요.</p>
          <div style={S.tableBox}>
            <table style={S.table}>
              <thead><tr style={S.headRow}><th>파일의 열</th><th>읽은 칸</th><th>값 예시</th></tr></thead>
              <tbody>
                {FIELDS.map(([k, label]) => {
                  const col = suggestion.mapping?.[k] ?? null;
                  if (col === null && (k === "status_col" || k === "option_col")) return null; // 선택 칸은 짝이 없으면 숨긴다
                  const low = suggestion.confidence?.[k] === "low";
                  return (
                    <tr key={k} style={S.row}>
                      <td>{col === null ? "-" : header(col)}</td>
                      <td>{label}{col === null && <strong style={{ color: "var(--color-destructive)" }}> 읽지 못함</strong>}
                        {low && <strong style={{ color: "var(--color-destructive)" }}> 확신 낮음</strong>}</td>
                      <td style={low ? { fontWeight: 600 } : undefined}>{(suggestion.samples?.[k] ?? []).join(", ") || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div style={ACTIONS}>
            <button type="button" className="primary-action" disabled={busy || [suggestion.mapping.product_col, suggestion.mapping.quantity_col, suggestion.mapping.date_col, suggestion.mapping.ref_col].some((v) => v === null)} onClick={confirmReading}>맞아요</button>
            <button type="button" disabled={busy} onClick={() => setSuggestion(null)}>다르게 읽혔어요</button>
          </div>
        </div>
      )}

      {info && !done && !reading && !suggestion && (
        <div style={S.sectionCard}>
          <h2 style={{ marginTop: 0 }}>2. 열 지정</h2>
          {notice && <p role="status" style={S.hint}>{notice}</p>}
          <p style={S.hint}>
            머리글이 비슷한 열은 미리 골라 두었습니다. 맞는지 확인하세요{" "}
            <InfoTip detail="날짜 열의 값이 그대로 출고일이 됩니다(시각은 버립니다). 고유 주문번호로 같은 주문이 두 번 반영되지 않게 막습니다." />
          </p>
          <h3 style={SUB}>필수</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("상품 코드(SKU)", "product")}
            {colSelect("수량", "quantity")}
            {colSelect("날짜(주문일·발송일)", "date")}
            {colSelect("고유 주문번호", "ref")}
          </div>
          <h3 style={SUB}>선택</h3>
          <div className="form-compact field-form" style={S.formGrid}>
            {colSelect("상태 (취소 주문 거르기)", "status", true)}
            {colSelect("옵션 (섞임 경고용)", "option", true)}
          </div>

          {cols.status !== NONE && info.status_values && (
            <fieldset style={{ ...BLOCK, border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", padding: "var(--space-sm) var(--space-md)" }}>
              <legend>
                반영할 상태 <span style={S.hint}>({header(Number(cols.status))})</span>{" "}
                <InfoTip detail="출고가 끝난 값(예: 배송중, 배송완료)만 고르세요. 고르지 않은 값은 건너뜁니다. 상태는 저장하지 않습니다." />
              </legend>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0 var(--space-lg)" }}>
                {info.status_values.map((v) => (
                  <label key={v.value} style={CHECK}>
                    <input type="checkbox" checked={statuses.includes(v.value)} disabled={busy}
                      onChange={(e) => { setStatuses(e.target.checked ? [...statuses, v.value] : statuses.filter((x) => x !== v.value)); setPreview(null); }} />
                    {v.value || "(빈 값)"} <span style={{ ...S.hint, fontVariantNumeric: "tabular-nums" }}>{v.count}건</span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

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
            <strong>반영 {preview.apply_count.toLocaleString()}건</strong> · 총 수량 {preview.total_quantity.toLocaleString()}
            {preview.date_from && <> · 날짜 {preview.date_from} ~ {preview.date_to}</>}
          </p>
          {preview.skipped.length > 0 && (
            <p style={{ ...S.hint, margin: "var(--space-xs) 0 0" }}>건너뜀 {preview.skipped_count}건: {preview.skipped.map((s) => `${s.message} ${s.count}건`).join(", ")}</p>
          )}
          {(() => { // 넣을 줄이 없고 이미 반영된 줄만 있으면, 버튼의 "반영할 행 없음"만으로는 이유가 안 보여 크게 알린다
            const already = preview.skipped.find((s) => s.reason === "ALREADY_IMPORTED")?.count ?? 0;
            return preview.apply_count === 0 && already > 0 && (
              <p role="status" style={{ ...S.ok, ...BLOCK }}>
                이 파일은 이미 모두 반영되었습니다 ({already.toLocaleString()}건). 다시 반영할 필요가 없습니다.
                {preview.problem_count > 0 && ` 문제 행 ${preview.problem_count}건은 파일에서 고친 뒤 다시 올리면 그 줄만 반영됩니다.`}
              </p>
            );
          })()}
          {preview.warnings.length > 0 && (
            <div role="alert" style={BLOCK}>
              {preview.warnings.map((w) => <p key={w.sku} style={{ ...S.error, margin: "0 0 var(--space-xs)" }}><strong>확인 필요</strong> {w.message} 색상·사이즈별로 재고를 따로 세려면 SKU를 나눠 등록하세요.</p>)}
            </div>
          )}

          {preview.problem_count > 0 && (
            <>
              <h3 style={{ ...SUB, color: "var(--color-destructive)" }}>문제 행 {preview.problem_count}건 {preview.problem_count > preview.problems.length && <span style={{ ...S.hint, fontWeight: 400 }}>(앞 {preview.problems.length}건만 표시)</span>}</h3>
              <div style={S.tableBox}>
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
            {preview.apply_count > 0 && (
              <label className="field" style={{ width: 200 }}>
                <span className="field-label">판매 채널 *</span>
                <select value={channel} disabled={busy} onChange={(e) => setChannel(e.target.value)} aria-invalid={!channel}>
                  <option value="">채널 선택</option>
                  {CHANNELS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </label>
            )}
            {preview.problem_count > 0 && preview.apply_count > 0 && (
              <label style={CHECK}>
                <input type="checkbox" checked={exclude} disabled={busy} onChange={(e) => setExclude(e.target.checked)} />
                문제 행 {preview.problem_count}건 제외하고 반영
              </label>
            )}
            <button type="button" className="primary-action" disabled={busy || !canCommit} aria-describedby={blockReason ? "commit-block-reason" : undefined} onClick={() => void commit()}>
              {busy ? "반영 중…" : preview.apply_count > 0 ? `${preview.apply_count.toLocaleString()}건 반영` : "반영할 행 없음"}
            </button>
            <InfoTip label="반영 전에 알아 둘 점" detail="반영한 이력은 되돌릴 수 없습니다(잘못된 건은 재고 현황에서 정정)." />
            {blockReason && <span id="commit-block-reason" style={S.hint}>{blockReason}</span>}
          </div>
        </div>
      )}

      {done && (
        <div style={S.sectionCard}>
          <p style={{ ...S.ok, marginTop: 0 }} role="status">
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

// 카드 안 간격: 같은 묶음은 좁게, 묶음 사이는 넓게
const BLOCK = { marginTop: "var(--space-md)" } as const;
const SUB = { margin: "var(--space-lg) 0 var(--space-sm)", fontSize: "var(--text-base)" } as const; // 카드 안 소제목
const ACTIONS = { display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "var(--space-sm) var(--space-md)", marginTop: "var(--space-lg)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--color-border)" } as const; // 반영 줄: 채널·체크·버튼·이유를 한 줄에
const CHECK = { display: "inline-flex", alignItems: "center", gap: "var(--space-xs)", minHeight: "var(--control-min)" } as const;
