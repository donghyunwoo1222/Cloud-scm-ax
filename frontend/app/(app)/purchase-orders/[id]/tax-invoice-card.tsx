"use client"; // 기록 폼·취소 입력·중복 클릭 잠금이 있어 브라우저에서 실행

// 발주서 상세의 "세금계산서 수취" 카드 (#268, 내부 전용): 공급업체 문서·메일·공개 확인 화면에는 나가지 않는다.
// 원가 카드와 별도 컴포넌트다. 값은 모두 서버(GET .../tax-invoices)의 대조 결과를 그대로 보여 주고, 기록 버튼은 서버의 can_record 만 따른다.
import { useCallback, useEffect, useState } from "react"; // 불러오기, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { Field } from "../../../lib/field"; // 모바일에서 라벨이 테두리에 걸리는 입력 항목
import { seoulToday } from "../../../lib/movement-form"; // 서울 기준 오늘
import { fmtTime, PoStatus } from "../../../lib/po"; // 서울 시각, 발주 상태 코드
import { StatusBadge } from "../../../lib/status-badge"; // 글자 + 아이콘 배지
import { S } from "../../../lib/styles"; // 화면 공통 스타일
import { useSubmitLock } from "../../../lib/submit-lock"; // 중복 클릭 잠금
import {
  differenceText, FREIGHT_NOTE, formProblem, parseWon, ROUNDING_NOTE, shouldFetchTaxInvoices, shouldShowCard, showRoundingNote,
  splitInvoices, statusBadge, TaxInvoice, taxInvoiceErrorText, TaxInvoiceView, taxMismatchNote, vatHint,
} from "../../../lib/tax-invoice"; // 문구·검사 순수 함수
import { useToast } from "../../../lib/toast"; // 성공 알림

const won = (n: number) => `${n.toLocaleString("ko-KR")}원`; // 쉼표 원 단위 글자
const EMPTY_FORM = { number: "", supply: "", tax: "", memo: "" }; // 기록 폼 처음 값 (발행일은 오늘로 따로 채운다)

// 계산서 한 장의 보조 줄 (작성자·시각·메모·세액 안내). 값이 없는 칸은 그리지 않는다
// stacked: 표 칸에서는 줄을 나눠 쌓고, 안내 문구는 작은 보조 글씨로 둔다 (압축 행은 기존 한 줄 흐름)
function InvoiceMeta({ inv, stacked = false }: { inv: TaxInvoice; stacked?: boolean }) {
  const note = taxMismatchNote(inv);
  const line = stacked ? { display: "block" as const } : {}; // 줄바꿈
  return (
    <>
      <span style={line}>{inv.created_by_name ? `${inv.created_by_name} · ` : ""}{fmtTime(inv.created_at)} 기록</span>
      {inv.memo && <span style={{ ...line, overflowWrap: "anywhere", color: "var(--color-foreground)" }}>메모: {inv.memo}</span>}
      {note && <span style={stacked ? { ...line, ...S.hint, fontSize: "var(--text-sm)", marginTop: "var(--space-xs)" } : undefined}>안내: {note}</span>}
    </>
  );
}

// receivedKey: 입고 수량이 바뀌면(입고·정정) 대조 결과를 다시 읽게 하는 값 (부모가 줄별 누적 입고량을 이어 붙여 준다)
export function TaxInvoiceCard({ orderId, status, receivedKey }: { orderId: string; status: PoStatus; receivedKey: string }) {
  const fetchable = shouldFetchTaxInvoices(status); // 작성 중·승인됨은 조회하지 않는다
  const [view, setView] = useState<TaxInvoiceView | null>(null); // 서버 대조 결과
  const [loadError, setLoadError] = useState(false); // 불러오기 실패
  const [open, setOpen] = useState(false); // 기록 폼을 펼쳤는지
  const [form, setForm] = useState(EMPTY_FORM); // 기록 폼 값 (실패해도 지우지 않는다)
  const [date, setDate] = useState(""); // 발행일 (화면이 열린 뒤 서울 오늘로 채운다)
  const [today, setToday] = useState(""); // 발행일 상한 (미래 날짜 선택 불가)
  const [formError, setFormError] = useState(""); // 기록 오류 문장
  const [showCancelled, setShowCancelled] = useState(false); // "취소된 n장" 펼침
  const [cancelFor, setCancelFor] = useState<number | null>(null); // 취소 사유를 입력 중인 계산서
  const [cancelReason, setCancelReason] = useState(""); // 취소 사유 (필수)
  const [cancelError, setCancelError] = useState(""); // 취소 오류 문장
  const saveLock = useSubmitLock(); // 기록 저장 중복 클릭 잠금
  const cancelLock = useSubmitLock(); // 취소 중복 클릭 잠금
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setView(await api<TaxInvoiceView>(`/purchase-orders/${orderId}/tax-invoices`));
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, [orderId]);

  useEffect(() => {
    if (!fetchable) return; // 계산서가 있을 수 없는 상태는 API 도 부르지 않는다
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    load();
    const t = seoulToday(); // 빌드 중 서버 시각을 읽지 않고 브라우저에서 날짜를 정한다
    setToday(t); setDate(t);
  }, [fetchable, load, status, receivedKey]); // 발주 상태·입고 수량이 바뀌면(입고 완료·정정 등) 다시 읽는다

  if (!fetchable) return null;
  if (loadError && !view) return <section aria-labelledby="tax-heading" style={S.sectionCard}><h2 id="tax-heading" style={{ marginTop: 0 }}>세금계산서 수취</h2><p role="alert" style={S.error}>세금계산서를 불러오지 못했어요. 화면을 새로 고쳐 주세요.</p></section>;
  if (!view || !shouldShowCard(status, view.items.length)) return null; // 취소된 발주에 계산서가 없으면 카드를 만들지 않는다

  const { summary, can_record: canRecord } = view;
  const badge = statusBadge(summary.status);
  const diff = differenceText(summary);
  const { active, cancelled } = splitInvoices(view.items);
  const hint = vatHint(form.supply);
  const problem = formProblem({ number: form.number, date, supply: form.supply, tax: form.tax }, today);
  const recordOpen = open && canRecord; // 서버가 기록을 막으면(상태가 바뀌면) 폼도 닫힌 것으로 본다

  async function save() {
    if (problem) { setFormError(problem); return; }
    await saveLock.run(async () => {
      setFormError("");
      try {
        const next = await api<TaxInvoiceView>(`/purchase-orders/${orderId}/tax-invoices`, {
          method: "POST",
          body: { invoice_number: form.number.trim(), issue_date: date, supply_amount: parseWon(form.supply), tax_amount: parseWon(form.tax), memo: form.memo.trim() || null },
        });
        setView(next); setForm(EMPTY_FORM); setDate(today); setOpen(false); // 성공: 폼을 비우고 접는다
        toast("세금계산서를 기록했어요");
      } catch (e) {
        setFormError(taxInvoiceErrorText(e)); // 서버 원문 대신 사유별 문장. 입력값은 그대로 둔다
        if ((e as { code?: string }).code === "INVALID_STATUS") load(); // 상태가 바뀌었으면 can_record 를 다시 읽는다
      }
    });
  }

  async function cancel(id: number) {
    if (!cancelReason.trim()) { setCancelError("취소 사유를 입력해 주세요."); return; }
    await cancelLock.run(async () => {
      if (!window.confirm("이 세금계산서를 취소할까요?\n취소해도 기록은 남고, 대조 합계에서만 빠집니다.")) return; // 확인창
      setCancelError("");
      try {
        setView(await api<TaxInvoiceView>(`/purchase-orders/${orderId}/tax-invoices/${id}/cancel`, { method: "POST", body: { reason: cancelReason.trim() } }));
        setCancelFor(null); setCancelReason("");
        toast("세금계산서를 취소 표시했어요");
      } catch (e) {
        setCancelError(taxInvoiceErrorText(e));
        if ((e as { code?: string }).code === "ALREADY_CANCELLED") load(); // 이미 취소됐으면 최신 상태로
      }
    });
  }

  return (
    <section aria-labelledby="tax-heading" className="tax-card" style={S.sectionCard}>
      <h2 id="tax-heading" style={{ marginTop: 0, marginBottom: "var(--space-xs)" }}>세금계산서 수취</h2>
      <p style={{ ...S.hint, margin: 0 }}>(내부용, 공급업체 문서·메일에는 나가지 않습니다)</p>

      {/* 요약: 입고 금액 / 받은 공급가액 / 결과 */}
      <dl className="info-strip flat">
        <div><dt>입고 금액</dt><dd>{won(summary.received_goods_krw)}</dd></div>
        <div><dt>받은 공급가액</dt><dd>{won(summary.supply_total)}</dd></div>
        <div><dt>대조 결과</dt><dd><StatusBadge kind={badge.kind}>{badge.text}</StatusBadge></dd></div>
      </dl>
      {diff && <p role="status" style={{ margin: "var(--space-sm) 0 0" }}><strong>{diff}</strong></p>}
      {showRoundingNote(summary) && <p style={{ ...S.hint, margin: "var(--space-sm) 0 0", fontSize: "var(--text-sm)" }}>{ROUNDING_NOTE}</p>}
      <p style={{ ...S.hint, margin: "var(--space-sm) 0 var(--space-sm)", fontSize: "var(--text-sm)" }}>{FREIGHT_NOTE}</p>

      {/* 유효한 계산서 목록: 데스크톱은 표, 좁은 화면은 압축 행 */}
      {active.length > 0 && (
        <>
          <div className="table-box table-view" style={{ marginTop: "var(--space-md)" }}>
            <table style={{ ...S.table, minWidth: 560 }}>
              <thead><tr style={S.headRow}><th>번호</th><th>발행일</th><th style={S.num}>공급가액</th><th style={S.num}>세액</th><th style={S.num}>합계</th><th>기록</th><th aria-label="동작"></th></tr></thead>
              <tbody>
                {active.map((inv) => (
                  <tr key={inv.id} style={S.row}>
                    <td style={{ overflowWrap: "anywhere" }}>{inv.invoice_number}</td>
                    <td style={S.nowrap}>{inv.issue_date}</td>
                    <td style={S.num}>{won(inv.supply_amount)}</td>
                    <td style={S.num}>{won(inv.tax_amount)}</td>
                    <td style={S.num}>{won(inv.total)}</td>
                    <td><InvoiceMeta inv={inv} stacked /></td>
                    <td><button type="button" className="danger-action" disabled={cancelLock.busy || cancelFor !== null} onClick={() => { setCancelFor(inv.id); setCancelReason(""); setCancelError(""); }}>취소</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="compact-block">
            <ul className="compact-list" aria-label="받은 세금계산서">
              {active.map((inv) => (
                <li key={inv.id} className="compact-row">
                  <div className="compact-main"><strong>{inv.invoice_number}</strong><span className="compact-value">{won(inv.total)}</span></div>
                  <div className="compact-sub"><span>{inv.issue_date}</span><span>공급가액 {won(inv.supply_amount)}</span><span>세액 {won(inv.tax_amount)}</span></div>
                  <div className="compact-sub"><InvoiceMeta inv={inv} /></div>
                  <p style={{ margin: "var(--space-xs) 0 0" }}><button type="button" className="danger-action" disabled={cancelLock.busy || cancelFor !== null} onClick={() => { setCancelFor(inv.id); setCancelReason(""); setCancelError(""); }}>취소</button></p>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
      {active.length === 0 && cancelled.length === 0 && <p style={{ ...S.hint, margin: "var(--space-sm) 0 0" }}>아직 받은 세금계산서가 없습니다.</p>}

      {/* 취소 입력: 사유 필수, 확인창 뒤에 처리 */}
      {cancelFor !== null && (
        <form style={{ ...S.panel, display: "block" }} aria-label="세금계산서 취소" onSubmit={(e) => { e.preventDefault(); cancel(cancelFor); }}>
          <label htmlFor="tax-cancel-reason">취소 사유 (필수)</label>
          <textarea id="tax-cancel-reason" rows={2} maxLength={500} style={{ display: "block", width: "100%" }} value={cancelReason} disabled={cancelLock.busy} onChange={(e) => setCancelReason(e.target.value)} />
          {cancelError && <p role="alert" style={S.error}>{cancelError}</p>}
          <p style={{ ...S.buttons, flexWrap: "wrap" }}>
            <button type="button" disabled={cancelLock.busy} onClick={() => { setCancelFor(null); setCancelError(""); }}>닫기</button>
            <button type="submit" className="danger-action" disabled={cancelLock.busy || !cancelReason.trim()}>{cancelLock.busy ? "취소 중…" : "취소 확정"}</button>
          </p>
        </form>
      )}

      {/* 취소한 계산서: 접어 두었다가 펼치면 흐리게 */}
      {cancelled.length > 0 && (
        <div style={{ marginTop: "var(--space-md)" }}>
          <button type="button" aria-expanded={showCancelled} onClick={() => setShowCancelled((v) => !v)}>{showCancelled ? "취소된 계산서 접기" : `취소된 ${cancelled.length}장 보기`}</button>
          {showCancelled && (
            <ul className="compact-list" style={{ display: "block", color: "var(--color-muted-foreground)" }} aria-label="취소된 세금계산서">
              {cancelled.map((inv) => (
                <li key={inv.id} className="compact-row">
                  <div className="compact-main"><strong>{inv.invoice_number}</strong><span className="compact-value">{won(inv.total)}</span></div>
                  <div className="compact-sub">
                    <span>발행 {inv.issue_date}</span>
                    <span>취소 {fmtTime(inv.cancelled_at)}{inv.cancelled_by_name ? ` · ${inv.cancelled_by_name}` : ""}</span>
                    {inv.cancel_reason && <span style={{ overflowWrap: "anywhere" }}>사유: {inv.cancel_reason}</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* 기록 폼: 서버의 can_record 가 참일 때만 버튼이 보인다 */}
      {canRecord && !recordOpen && <p style={{ marginBottom: 0 }}><button type="button" disabled={cancelFor !== null} onClick={() => { setFormError(""); setOpen(true); }}>세금계산서 기록</button></p>}
      {recordOpen && (
        <form className="form-compact field-form" style={S.panel} aria-label="세금계산서 기록" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <Field label="계산서 번호 *" className="field-half"><input value={form.number} maxLength={50} disabled={saveLock.busy} onChange={(e) => setForm({ ...form, number: e.target.value })} /></Field>
          <Field label="발행일 *" className="field-half"><input type="date" value={date} max={today} disabled={saveLock.busy} onChange={(e) => setDate(e.target.value)} /></Field>
          <Field label="공급가액(원) *" className="field-half"><input inputMode="numeric" value={form.supply} disabled={saveLock.busy} onChange={(e) => setForm({ ...form, supply: e.target.value })} /></Field>
          <Field label="세액(원) *" className="field-half"><input inputMode="numeric" value={form.tax} disabled={saveLock.busy} onChange={(e) => setForm({ ...form, tax: e.target.value })} /></Field>
          {hint !== null && <p style={{ ...S.hint, ...S.basisFull, margin: 0 }}>공급가액의 10%는 {won(hint)}입니다. 세액이 달라도 저장할 수 있어요.</p>}
          <Field label="메모(선택)"><input value={form.memo} maxLength={1000} disabled={saveLock.busy} onChange={(e) => setForm({ ...form, memo: e.target.value })} /></Field>
          {formError && <p role="alert" style={{ ...S.error, ...S.basisFull, margin: 0 }}>{formError}</p>}
          <p className="form-actions" style={{ ...S.buttons, ...S.basisFull, margin: 0 }}>
            <button type="button" disabled={saveLock.busy} onClick={() => { setOpen(false); setFormError(""); }}>닫기</button>
            <button type="submit" className="primary-action" disabled={saveLock.busy}>{saveLock.busy ? "저장 중…" : "저장"}</button>
          </p>
        </form>
      )}
    </section>
  );
}
