"use client"; // 버튼·상태를 다루는 화면이라 브라우저에서 실행

import { useCallback, useEffect, useState } from "react"; // 처음 한 번 불러오기, 함수 고정, 상태

import { ApiError, api } from "../../lib/api"; // 공통 API 호출 함수·오류 종류
import { StatusBadge } from "../../lib/status-badge"; // 연결 상태 배지
import { S } from "../../lib/styles"; // 화면 공통 스타일
import { useToast } from "../../lib/toast"; // 성공 알림 토스트

// GET /api/v1/slack/link 응답 (회사·사용자는 로그인 토큰으로만 정해진다)
type Info = {
  enabled: boolean; // 서버에서 슬랙 연동이 켜져 있는지
  status: "NONE" | "PENDING" | "LINKED"; // 연결 없음 / 코드 받음(연결 전) / 연결됨
  code_expires_at: string | null; // PENDING 일 때 코드 만료 시각
  slack_user_id: string | null; // 연결된 슬랙 사용자 id
  linked_at: string | null; // 연결된 시각
};
type Issued = { code: string; expires_at: string }; // POST /slack/link/code 응답: 코드 원문은 이 응답에만 나온다

const BOT = "scm-order-bot"; // 안내 문구에 쓰는 슬랙 봇 이름
const GENERIC = "처리하지 못했어요. 잠시 뒤 다시 시도해 주세요."; // 알 수 없는 실패
const when = (iso: string) => new Date(iso).toLocaleString("ko-KR"); // 예) "2026. 11. 15. 오후 3:30:00"

// 슬랙 연결 화면 (주소 /slack): 관리자·담당자 모두 자기 연결만 다룬다
export default function SlackPage() {
  const toast = useToast(); // 성공 알림 토스트
  const [info, setInfo] = useState<Info | null>(null); // 서버 상태 (불러오기 전에는 null)
  // 방금 받은 코드. 화면 상태로만 가진다(저장소·주소·로그에 넣지 않는다). 화면을 벗어나거나 새로 열면 사라진다
  const [issued, setIssued] = useState<Issued | null>(null);
  const [checkedAt, setCheckedAt] = useState(0); // 서버 상태를 마지막으로 가져온 시각(ms)
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 막아 연속 클릭을 방지한다
  const [error, setError] = useState(""); // 화면에 보일 오류 문장

  // 상태만 다시 가져온다. 서버가 아직 PENDING 이면 화면의 코드는 그대로 두고, 연결됐거나(LINKED) 없으면 코드를 숨긴다
  const apply = useCallback((next: Info) => {
    setInfo(next);
    setCheckedAt(Date.now()); // 만료 비교 기준 시각 (렌더 중에 시계를 읽지 않으려고 상태로 둔다)
    if (next.status !== "PENDING") setIssued(null);
  }, []);
  const load = useCallback(() => api<Info>("/slack/link").then(apply), [apply]);

  // 실패를 화면 문장으로 바꾼다. 409(이미 연결)·503(꺼짐)은 상태가 바뀐 것이니 다시 가져와 화면을 맞춘다
  async function fail(e: unknown) {
    if (e instanceof ApiError && e.code === "SLACK_ALREADY_LINKED") setError("이미 연결돼 있어요. 먼저 연결을 해제해 주세요.");
    else if (e instanceof ApiError && e.code === "SLACK_DISABLED") setError("슬랙 연결은 아직 켜져 있지 않아요.");
    else setError(GENERIC);
    if (e instanceof ApiError && (e.status === 409 || e.status === 503)) await load().catch(() => {});
  }

  // 버튼 동작 공통: 요청 중 잠금 → 실행 → 실패하면 문장 표시
  async function run(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try { await action(); } catch (e) { await fail(e); } finally { setBusy(false); }
  }

  useEffect(() => {
    api<Info>("/slack/link").then(apply).catch(() => setError(GENERIC));
  }, [apply]);

  // 슬랙에서 연결을 끝냈는지 눈으로 확인하려고 직접 누른다 (자동 반복 조회는 없다). 눌렀는데 화면이 그대로면 헷갈리니 결과를 토스트로 알려 준다
  const refresh = () => run(async () => {
    const next = await api<Info>("/slack/link");
    apply(next);
    if (next.status === "LINKED") toast("슬랙 연결이 확인됐어요");
    else if (next.status === "PENDING" && next.code_expires_at && new Date(next.code_expires_at).getTime() > Date.now()) toast("아직 연결되지 않았어요. 슬랙에서 코드를 보냈는지, 그 슬랙 계정이 다른 SCM 계정에 이미 연결돼 있지 않은지 확인해 주세요"); // 만료됐으면 화면의 만료 안내가 대신 말해 준다
  });

  const issue = () => run(async () => {
    const got = await api<Issued>("/slack/link/code", { method: "POST" });
    setIssued(got); // 코드 원문은 여기서만 받는다
    setInfo((prev) => (prev ? { ...prev, status: "PENDING", code_expires_at: got.expires_at } : prev));
  });

  // 대기 중인 코드를 지운다 (연결 해제와 같은 API 지만 연결된 게 없으니 확인창 없이 바로)
  const cancelCode = () => run(async () => {
    apply(await api<Info>("/slack/link/unlink", { method: "POST" }));
    toast("코드를 취소했어요");
  });

  const unlink = () => run(async () => {
    if (!window.confirm("슬랙 연결을 해제할까요? 해제하면 슬랙에서 이 계정으로 요청할 수 없어요.")) return; // 확인 한 번 (취소하면 아무 일도 없다)
    apply(await api<Info>("/slack/link/unlink", { method: "POST" })); // 해제 응답이 새 상태다 (코드도 함께 숨겨진다)
    toast("슬랙 연결을 해제했어요");
  });

  const expired = info?.code_expires_at ? new Date(info.code_expires_at).getTime() < checkedAt : false; // 코드 만료 여부

  // 상태별 배지: 연결 안 됨 / 연결 대기 / 연결됨 (색 + 글자 + 아이콘)
  const badge = !info ? null
    : info.status === "LINKED" ? <StatusBadge kind="ok">연결됨</StatusBadge>
    : info.status === "PENDING" ? <StatusBadge kind="info">연결 대기</StatusBadge>
    : <StatusBadge kind="unknown" icon="cancelled">연결 안 됨</StatusBadge>;

  const copy = (text: string) => navigator.clipboard.writeText(text).then(() => toast("복사했어요"), () => setError("복사하지 못했어요. 직접 입력해 주세요."));

  return (
    <section>
      <h1>슬랙 연결</h1>
      <p style={S.hint}>슬랙에서 {BOT}에게 재고·발주를 물어보려면 이 계정과 슬랙을 한 번 연결해야 해요.</p>
      {error && <p role="alert" style={S.error}>{error}</p>}
      {!info && !error && <p style={S.hint}>불러오는 중…</p>}
      {info && (
        <div style={{ ...S.sectionCard, maxWidth: 640 }}>
          <div className="slack-head">
            <h2 style={{ margin: 0 }}>연결 상태</h2>
            {badge}
            <button type="button" className="text-button" style={{ marginInlineStart: "auto" }} onClick={refresh} disabled={busy}>새로고침</button>
          </div>

          {!info.enabled && info.status !== "LINKED" && <p style={S.hint}>슬랙 연결은 아직 켜져 있지 않아요. 관리자에게 문의해 주세요.</p>}

          {info.enabled && info.status === "NONE" && (
            <>
              <ol className="slack-steps">
                <li><b>연결 코드 받기</b>를 눌러 6자리 코드를 받아요.</li>
                <li>슬랙에서 {BOT}에게 <code>연결 코드</code>를 보내요. (10분 안에)</li>
                <li>여기로 돌아와 <b>새로고침</b>을 누르면 연결이 확인돼요.</li>
              </ol>
              <div className="slack-actions">
                <button type="button" className="primary-action" onClick={issue} disabled={busy}>연결 코드 받기</button>
              </div>
            </>
          )}

          {info.enabled && info.status === "PENDING" && (
            <>
              {issued ? (
                <>
                <ol className="slack-steps">
                  <li>아래 문구를 복사해 슬랙에서 {BOT}에게 보내요.</li>
                  <li>보낸 뒤 <b>연결 확인</b>을 눌러요.</li>
                </ol>
                <div className="slack-code">
                  <div className="slack-code-row">
                    <code aria-label="연결 코드">연결 {issued.code}</code>
                    <button type="button" onClick={() => void copy(`연결 ${issued.code}`)}>복사</button>
                  </div>
                  <span style={S.kpiSub}>만료 {when(issued.expires_at)} · 이 화면을 벗어나면 코드를 다시 볼 수 없어요.</span>
                </div>
                </>
              ) : expired ? (
                <div className="slack-notice" role="status">
                  <b>코드가 만료됐어요</b>
                  <span>새 코드를 받아 다시 연결해 주세요.</span>
                </div>
              ) : (
                <div className="slack-notice" role="status">
                  <b>아직 연결되지 않았어요</b>
                  <span>{info.code_expires_at && `만료 ${when(info.code_expires_at)} · `}코드를 잃어버렸다면 새로 받아 주세요.</span>
                </div>
              )}
              <div className="slack-actions">
                {/* 코드를 보낸 직후에는 "연결 확인"이 주요 동작, 새 코드는 보조. 만료됐을 때는 새 코드가 유일한 할 일이라 파란 버튼 */}
                {issued && <button type="button" className="primary-action" onClick={refresh} disabled={busy}>연결 확인</button>}
                <button type="button" className={issued ? "text-button" : expired ? "primary-action" : undefined} onClick={issue} disabled={busy}>새 코드 받기</button>
                <button type="button" className="text-button" onClick={cancelCode} disabled={busy}>코드 취소</button>
                <span style={{ ...S.kpiSub, flexBasis: issued ? "100%" : undefined }}>새 코드를 받으면 이전 코드는 더 이상 쓸 수 없어요.</span>
              </div>
            </>
          )}

          {info.status === "LINKED" && (
            <>
              <div className="slack-linked" role="status">
                <b>슬랙과 연결돼 있어요</b>
                <span>이제 슬랙에서 {BOT}에게 바로 요청할 수 있어요.</span>
              </div>
              <dl className="slack-facts">
                <div><dt style={S.detailLabel}>슬랙 사용자 id</dt><dd>{info.slack_user_id}</dd></div>
                <div><dt style={S.detailLabel}>연결 시각</dt><dd>{info.linked_at && when(info.linked_at)}</dd></div>
              </dl>
              <div className="slack-actions slack-unlink">
                <button type="button" onClick={unlink} disabled={busy}>연결 해제</button>
                <span style={S.kpiSub}>해제하면 슬랙에서 이 계정으로 요청할 수 없어요.</span>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
