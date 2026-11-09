"use client"; // 입력·확인창·발송 버튼이 있는 부분이라 브라우저에서 실행

import Link from "next/link"; // 공급업체 이메일 넣으러 가기
import { useEffect, useState } from "react"; // 미리보기 불러오기, 상태

import { api, ApiError } from "../../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../../lib/list"; // 오류 문장
import { fmtTime } from "../../../../lib/po"; // 시각 표시 (서울 기준)
import { S } from "../../../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/purchase-orders/{id}/email 응답 (#158). 받는 사람·제목·고정 부분은 서버가 만들고, 앞머리만 고친다.
type Preview = {
  to: string | null; supplier_id: number; reply_to: string; subject: string; intro: string; fixed_html: string;
  attachments: string[]; status: "APPROVED" | "ORDERED"; emailed_at: string | null; emailed_to: string | null; mail_ready: boolean;
};
type Sent = { emailed_at: string; emailed_to: string }; // 발송 응답(발주서)에서 쓰는 칸

const INTRO_MAX = 2000; // 앞머리 최대 글자 수 (서버와 같은 값)

export function MailPanel({ id, onSent }: { id: string; onSent: () => void }) {
  const [preview, setPreview] = useState<Preview | null>(null); // 미리보기 값
  const [intro, setIntro] = useState(""); // 사용자가 고치는 앞머리
  const [error, setError] = useState<unknown>(null); // 불러오기·발송 오류
  const [busy, setBusy] = useState(false); // 보내는 중 (더블클릭 막기, 서버도 잠금으로 한 번 더 막는다)
  const [sent, setSent] = useState<Sent | null>(null); // 방금 보낸 결과
  const [version, setVersion] = useState(0); // 바꾸면 미리보기를 다시 불러온다

  useEffect(() => {
    api<Preview>(`/purchase-orders/${id}/email`).then((p) => { setPreview(p); setIntro(p.intro); }).catch(setError);
  }, [id, version]); // 보낸 뒤 다시 불러와 상태(ORDERED)와 마지막 발송 기록을 갱신한다

  if (!preview) return <div className="no-print" style={S.card}><ErrorText error={error} />{!error && <p>미리보기를 불러오는 중…</p>}</div>;

  const resend = preview.status === "ORDERED"; // 이미 발주함: 확인창에서 한 번 더 묻는다
  const blocked = !preview.to ? "공급업체 이메일이 없어 보낼 수 없습니다." : !preview.mail_ready ? "메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요." : !intro.trim() ? "앞머리 문단을 적어 주세요." : "";

  async function send() {
    if (!preview?.to) return;
    const question = resend
      ? `이미 발주함 상태인 발주서입니다${preview.emailed_at ? ` (마지막 발송 ${fmtTime(preview.emailed_at)}, ${preview.emailed_to})` : ""}.\n${preview.to}로 다시 보낼까요? 발송 기록은 이번 것으로 바뀝니다.`
      : `${preview.to}로 발주서를 보냅니다.\n보내면 발주서가 발주함(ORDERED) 상태로 바뀝니다. 보낼까요?`;
    if (!window.confirm(question)) return; // 확인창
    setBusy(true);
    setError(null);
    try {
      const order = await api<Sent>(`/purchase-orders/${id}/email`, { method: "POST", body: { intro, resend } });
      setSent({ emailed_at: order.emailed_at, emailed_to: order.emailed_to });
      setVersion((v) => v + 1);
      onSent(); // 문서 화면의 상태도 다시 읽는다
    } catch (e) {
      setError(e);
      if (e instanceof ApiError && e.code === "ALREADY_ORDERED") setVersion((v) => v + 1); // 다른 사람이 먼저 보냈다: 미리보기를 다시 불러 상태를 맞춘다
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="no-print" style={{ ...S.card, marginBottom: "var(--space-md)", display: "grid", gap: "var(--space-sm)" }}>
      <h2 style={{ margin: 0 }}>메일 미리보기</h2>
      <dl style={{ margin: 0, display: "grid", gridTemplateColumns: "auto 1fr", gap: "var(--space-xs) var(--space-md)" }}>
        <dt style={S.hint}>받는 사람</dt>
        <dd style={{ margin: 0 }}>
          {preview.to ?? (
            <span role="alert" style={S.error}>
              공급업체 이메일이 없습니다. <Link href={`/suppliers?edit=${preview.supplier_id}`}>공급업체 정보에서 이메일을 넣어 주세요.</Link>
            </span>
          )}
        </dd>
        <dt style={S.hint}>답장 받는 주소</dt><dd style={{ margin: 0 }}>{preview.reply_to} (나)</dd>
        <dt style={S.hint}>제목</dt><dd style={{ margin: 0 }}>{preview.subject}</dd>
        <dt style={S.hint}>첨부</dt><dd style={{ margin: 0 }}>{preview.attachments.join(", ")}</dd>
        {preview.emailed_at && (<><dt style={S.hint}>마지막 발송</dt><dd style={{ margin: 0 }}>{fmtTime(preview.emailed_at)} → {preview.emailed_to}</dd></>)}
      </dl>
      <label style={{ maxWidth: "none" }}>{/* 공통 라벨은 폭 320px 상한: 문단 칸은 카드 폭 전체를 쓴다 */}
        앞머리 문단 (이 부분만 고칠 수 있습니다)
        <textarea value={intro} onChange={(e) => setIntro(e.target.value)} rows={4} maxLength={INTRO_MAX} style={{ width: "100%" }} />
      </label>
      <p style={{ ...S.hint, margin: 0 }}>아래 품목표·합계·발주 조건은 발주서와 같은 값으로 고정됩니다.</p>
      {/* 서버가 만든 고정 부분을 그대로 보여 준다. sandbox 에 allow-scripts 가 없어 안의 글자는 스크립트로 실행되지 않는다
          (값은 서버가 이미 escape 했다. 완전히 빈 sandbox 는 일부 브라우저에서 내용을 그리지 않아 allow-same-origin 만 연다) */}
      <iframe title="메일 고정 부분 미리보기" sandbox="allow-same-origin" srcDoc={`<div style="font-family:sans-serif">${preview.fixed_html}</div>`}
        style={{ width: "100%", height: 360, border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", background: "#fff" }} />
      {!preview.mail_ready && <p role="alert" style={{ ...S.error, margin: 0 }}>메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요.</p>}
      <div style={S.buttons}>
        <button type="button" className="primary-action" onClick={send} disabled={busy || !!blocked} aria-describedby={blocked ? "mail-blocked" : undefined}>
          {busy ? "보내는 중…" : resend ? "다시 보내기" : "메일 보내기"}
        </button>
        {blocked && <span id="mail-blocked" style={S.hint}>{blocked}</span>}
      </div>
      {sent && (
        <p role="status" style={{ ...S.ok, margin: 0 }}>
          {fmtTime(sent.emailed_at)}에 {sent.emailed_to}로 보냈습니다. 발주서는 발주함 상태입니다. (메일 서버로 보낸 것까지만 확인되며, 공급업체가 받았는지는 알 수 없습니다.)
        </p>
      )}
      <ErrorText error={error} />
    </div>
  );
}
