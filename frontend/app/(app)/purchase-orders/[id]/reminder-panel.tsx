"use client"; // 앞머리 입력·확인창·발송 버튼이 있어 브라우저에서 실행

import Link from "next/link"; // 공급업체 이메일 넣으러 가기
import { useEffect, useReducer, useState } from "react"; // 미리보기 불러오기, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { fmtTime } from "../../../lib/po"; // 서울 시각
import { blockedText, NO_ERRORS, panelErrors, REMINDER_INTRO_MAX, reminderErrorText, ReminderPreview } from "../../../lib/reminder"; // 미리보기 모양, 오류 문장
import { S } from "../../../lib/styles"; // 화면 공통 스타일
import { useSubmitLock } from "../../../lib/submit-lock"; // 중복 클릭 잠금

// 서버 오류(ApiError)를 문장으로: 서버 원문 대신 reminderErrorText 의 문장을 쓴다
const textOf = (e: unknown) => (e && typeof e === "object" && "code" in e ? reminderErrorText(e as Parameters<typeof reminderErrorText>[0]) : "알 수 없는 오류가 났습니다.");

// 납기 독촉 메일 패널 (#269). 서버의 allowed_actions 에 remind 가 있을 때만 부모가 연다
// 미리보기(GET)는 아무것도 바꾸지 않는다. 담당자가 확인창에서 확인해야만 POST 로 나간다
export function ReminderPanel({ id, onChanged, onSent, onClose }: { id: string; onChanged: () => void; onSent: () => void; onClose: () => void }) {
  const [preview, setPreview] = useState<ReminderPreview | null>(null); // 미리보기 값
  const [intro, setIntro] = useState(""); // 사용자가 고치는 앞머리
  const [errors, dispatch] = useReducer(panelErrors, NO_ERRORS); // 발송 오류·불러오기 오류·저장 실패 표시 (규칙은 lib/reminder.ts)
  const { run, busy } = useSubmitLock(); // 보내는 중 (더블클릭 막기, 서버도 발주서 잠금으로 한 번 더 막는다)
  const [version, setVersion] = useState(0); // 바꾸면 미리보기를 다시 불러온다

  useEffect(() => {
    api<ReminderPreview>(`/purchase-orders/${id}/reminder`)
      .then((p) => { setPreview(p); setIntro((cur) => cur || p.intro); dispatch({ type: "load-ok" }); }) // 고치던 앞머리는 다시 불러와도 지우지 않는다
      .catch((e) => dispatch({ type: "load-fail", text: textOf(e) }));
  }, [id, version]); // 보낸 뒤 다시 불러와 횟수·다음 가능 시각을 갱신한다

  const header = (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <h2 style={{ margin: 0 }}>납기 독촉 메일</h2>
      <button type="button" onClick={onClose} disabled={busy}>닫기</button>
    </div>
  );
  if (!preview) return <div style={S.sectionCard}>{header}{errors.loadError ? <p role="alert" style={S.error}>{errors.loadError}</p> : <p>미리보기를 불러오는 중…</p>}</div>;

  const limitText = blockedText(preview); // 간격·횟수·하루 상한에 걸렸을 때 이유
  const blocked = errors.unsaved ? "메일은 이미 나갔습니다. 다시 보내지 마세요."
    : !preview.to ? "공급업체 이메일이 없어 보낼 수 없습니다."
    : !preview.mail_ready ? "메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요."
    : limitText || (!intro.trim() ? "앞머리 문단을 적어 주세요." : "");

  // 확인창부터 잠금 안에서 연다: 보내는 중 온 클릭은 무시하고, 확인창을 취소하면 바로 풀린다
  const send = () => run(doSend);

  async function doSend() {
    if (!preview?.to) return;
    if (!window.confirm(`${preview.to}로 독촉 메일을 보낼까요?\n보내면 되돌릴 수 없고, 발송 기록이 남습니다.`)) return; // 확인창
    dispatch({ type: "send-start" });
    try {
      await api(`/purchase-orders/${id}/reminder`, { method: "POST", body: { intro } });
      onChanged(); // 이력과 발주서를 다시 읽는다
      onSent(); // 성공: 부모가 패널을 닫는다 (앞머리 글도 함께 사라진다)
    } catch (e) {
      dispatch({ type: "send-fail", text: textOf(e), code: (e as { code?: string }).code }); // 서버 원문은 쓰지 않는다. MAIL_SENT_NOT_SAVED 면 unsaved 가 켜진다
      onChanged(); // 실패도 이력에 남고, 상태가 바뀌었을 수 있어 다시 읽는다
      setVersion((v) => v + 1); // 횟수·다음 가능 시각을 다시 불러온다
    }
  }

  return (
    <div style={{ ...S.sectionCard, display: "grid", gap: "var(--space-sm)" }}>
      {header}
      {/* 미리보기는 아무것도 바꾸지 않는다는 것을 화면에도 적는다 */}
      <p role="status" style={{ ...S.hint, margin: 0 }}>미리보기입니다. 아직 발송되지 않았습니다. 아래 &ldquo;독촉 메일 보내기&rdquo;를 누르고 확인창에서 확인해야만 나갑니다.</p>
      <dl className="mail-head">
        <div>
          <dt>받는 사람</dt>
          <dd>
            {preview.to ? <b>{preview.to}</b> : (
              <span role="alert" style={S.error}>
                공급업체 이메일이 없습니다. <Link href={`/suppliers?edit=${preview.supplier_id}`}>공급업체 정보에서 이메일 넣기</Link>
              </span>
            )}
          </dd>
        </div>
        <div><dt>답장 주소</dt><dd>{preview.reply_to} <span style={S.hint}>(나에게 답장이 옵니다)</span></dd></div>
        <div><dt>제목</dt><dd><b>{preview.subject}</b></dd></div>
        <div>
          <dt>링크</dt>
          <dd>{preview.with_link ? "새 확인 링크가 들어갑니다. 보내면 이전 메일의 링크는 쓸 수 없게 됩니다." : "확인 링크는 들어가지 않습니다."}</dd>
        </div>
        <div>
          <dt>독촉 횟수</dt>
          <dd>{preview.sent_count}/{preview.max_per_order}번{preview.last_sent_at && ` (마지막 ${fmtTime(preview.last_sent_at)})`}</dd>
        </div>
      </dl>
      <label style={{ maxWidth: "none" }}>
        <span>본문 첫 문단 <span style={S.hint}>· 이 문단만 고칠 수 있습니다</span></span>
        <textarea value={intro} onChange={(e) => setIntro(e.target.value)} rows={3} maxLength={REMINDER_INTRO_MAX} spellCheck={false} style={{ width: "100%" }} />
      </label>
      <p style={{ ...S.hint, margin: 0 }}>본문 나머지 (납기와 아직 도착하지 않은 품목·남은 수량은 서버가 지금 값으로 채웁니다)</p>
      {/* 서버가 만든 고정 부분을 그대로 보여 준다 (메일 보내기 패널과 같은 sandbox 방식) */}
      <iframe title="독촉 메일 고정 부분 미리보기" sandbox="allow-same-origin" srcDoc={`<div style="font-family:sans-serif">${preview.fixed_html}</div>`}
        style={{ width: "100%", height: 320, border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)", background: "#fff" }} />
      <div style={S.buttons}>
        <button type="button" className="primary-action" onClick={send} disabled={busy || !!blocked} aria-describedby={blocked ? "reminder-blocked" : undefined}>
          {busy ? "보내는 중…" : "독촉 메일 보내기"}
        </button>
        {blocked && <span id="reminder-blocked" style={S.hint}>{blocked}</span>}
      </div>
      {errors.sendError && <p role="alert" style={S.error}>{errors.sendError}</p>}
      {errors.loadError && <p role="alert" style={S.error}>{errors.loadError}</p>}
    </div>
  );
}
