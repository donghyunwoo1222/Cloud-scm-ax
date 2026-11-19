"use client"; // 주소의 # 뒤를 읽고 클릭을 다루므로 브라우저에서 실행

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ApiError } from "../lib/api";
import { S } from "../lib/styles";
import { useSubmitLock } from "../lib/submit-lock";
import { confirmReply, viewReply } from "../lib/supplier-reply-api";
import {
  confirmText, dateRange, errorMessage, EXHAUSTED_NOTICE, screenOf, SUBMIT_LABEL, type ReplyView,
} from "../lib/supplier-reply";

const fmtTime = (iso: string) => new Date(iso).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }); // 확인 시각(서울)

// 공급업체 확인 화면 (주소 /supplier-reply#토큰, 로그인 없음). 토큰은 메모리 상태로만 쓰고 어디에도 저장·출력하지 않는다
export default function SupplierReplyPage() {
  const [token, setToken] = useState<string | null>(null); // null = 아직 읽기 전
  const [data, setData] = useState<ReplyView | null>(null);
  const [error, setError] = useState(""); // 불러오기 실패 문구 (화면 전체 대체)
  const [formError, setFormError] = useState(""); // 전송 실패 문구
  const [done, setDone] = useState(false); // 방금 보냈는지
  const [date, setDate] = useState(""); // 입력한 회신 납기 (빈 값으로 시작)
  const [range, setRange] = useState<{ min: string; max: string } | null>(null);
  const { run, busy } = useSubmitLock();

  // 주소의 # 뒤 값을 읽는다(서버 렌더에는 없으므로 effect 안에서만). 주소창의 # 는 지우지 않는다(새로고침해도 다시 열리게)
  useEffect(() => {
    const read = () => setToken(window.location.hash.slice(1));
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);

  const load = useCallback(async (t: string) => {
    try {
      setData(await viewReply(t));
      setError("");
      setRange(dateRange());
    } catch (e) {
      setData(null);
      setError(e instanceof ApiError ? errorMessage(e.code, e.message) : errorMessage("", ""));
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 토큰을 읽은 뒤 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    if (token) void load(token);
  }, [token, load]);

  async function send() {
    if (!token || !data) return;
    if (!window.confirm(confirmText(date, data.replies_left ?? 0))) return;
    await run(async () => {
      setFormError("");
      try {
        setData(await confirmReply(token, date || undefined)); // 응답이 view 와 같은 모양이라 그대로 갱신
        setDate("");
        setDone(true);
      } catch (e) {
        setDone(false);
        const err = e instanceof ApiError ? e : null;
        setFormError(errorMessage(err?.code ?? "", err?.message ?? ""));
        if (err && (err.code === "SUPPLIER_REPLY_CLOSED" || err.code === "SUPPLIER_REPLY_LIMIT")) void load(token); // 상태가 바뀐 것이므로 최신으로
      }
    });
  }

  const shell = (children: ReactNode) => (
    <main style={{ maxWidth: 720, margin: "0 auto", padding: "var(--page-pad)", width: "100%" }}>
      <h1>발주 확인</h1>
      {children}
    </main>
  );

  if (token === null) return shell(<p style={S.hint}>불러오는 중…</p>);
  if (!token) return shell(<p role="status">메일의 링크로 들어와 주세요.</p>);
  if (error) {
    return shell(<>
      <p role="alert" style={S.loginAlert}>{error}</p>
      <p><button type="button" onClick={() => { setError(""); void load(token); }}>다시 시도</button></p>
    </>);
  }
  if (!data) return shell(<p style={S.hint}>불러오는 중…</p>);

  const screen = screenOf(data);
  if (screen === "NOTICE") {
    // 취소는 서버가 다른 칸을 비워 준다. 입고 완료류는 발주 정보도 함께 보인다
    return shell(<>
      <p role="status" style={S.card}>{data.state === "RECEIVED" ? "입고 완료된 발주입니다" : data.notice}</p>
      {data.state !== "CANCELLED" && <Info data={data} />}
    </>);
  }

  return shell(<>
    <Info data={data} />
    {done && <p role="status" style={{ ...S.card, marginTop: "var(--space-md)" }}>확인했습니다. 담당자에게 전달되었습니다.</p>}
    {formError && <p role="alert" style={{ ...S.loginAlert, marginTop: "var(--space-md)" }}>{formError}</p>}
    {screen === "EXHAUSTED" ? (
      <p role="status" style={{ ...S.card, marginTop: "var(--space-md)" }}>{EXHAUSTED_NOTICE}</p>
    ) : (
      <section style={{ ...S.card, marginTop: "var(--space-md)", display: "grid", gap: "var(--space-md)" }}>
        {screen === "RECONFIRM" && <p>이미 확인하셨습니다. 납기만 바꿔 다시 보내실 수 있습니다.</p>}
        <p style={S.hint}>남은 회신 횟수 {data.replies_left}번 (납기를 바꿀 때만 줄어듭니다)</p>
        <label>
          회신 납기{screen === "FIRST" ? " (선택)" : ""}
          <input type="date" value={date} min={range?.min} max={range?.max} onChange={(e) => setDate(e.target.value)} />
        </label>
        <button type="button" className="primary-action" disabled={busy || (screen === "RECONFIRM" && !date)} onClick={() => void send()}>
          {busy ? "보내는 중…" : SUBMIT_LABEL[screen]}
        </button>
      </section>
    )}
  </>);
}

// 발주 정보와 품목 표 (단가·금액 없음)
function Info({ data }: { data: ReplyView }) {
  return (
    <section style={S.card}>
      <p><strong>{data.buyer_name}</strong> 발주서 {data.po_number}</p>
      <dl style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-xs) var(--space-md)", margin: "var(--space-md) 0" }}>
        {data.order_date && <><dt>발주일</dt><dd>{data.order_date}</dd></>}
        {data.due_date && <><dt>약속 납기</dt><dd>{data.due_date}</dd></>}
        {data.supplier_due_date && <><dt>회신 납기</dt><dd>{data.supplier_due_date}</dd></>}
        {data.supplier_confirmed_at && <><dt>확인 시각</dt><dd>{fmtTime(data.supplier_confirmed_at)}</dd></>}
      </dl>
      <div className="table-box">
        <table>
          <thead><tr><th>품목</th><th>옵션</th><th>수량</th><th>단위</th></tr></thead>
          <tbody>
            {data.items.map((i, n) => (
              <tr key={n}><td>{i.name}</td><td>{i.options ?? "-"}</td><td>{i.quantity}</td><td>{i.unit ?? "-"}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
