"use client"; // 더 보기 버튼을 다루므로 브라우저에서 실행

import { useCallback, useEffect, useRef, useState } from "react"; // 상태, 요청 번호 보관

import { apiList, Meta } from "../../../lib/api"; // 목록 호출 (data + meta)
import { EmailLog, kindLabel, resultText } from "../../../lib/email-log"; // 이력 모양과 문장 표
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { fmtTime } from "../../../lib/po"; // 서울 시각
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// 메일 발송 이력 섹션 (최신순, 20건씩 더 보기). refreshKey 가 바뀌면 처음부터 다시 불러온다 (변경 이력과 같은 방식)
export function EmailLogSection({ orderId, refreshKey }: { orderId: string; refreshKey: number }) {
  const [rows, setRows] = useState<EmailLog[] | null>(null); // 불러온 행 (null = 아직)
  const [meta, setMeta] = useState<Meta | null>(null); // 마지막으로 받은 쪽 정보
  const [error, setError] = useState<unknown>(null); // 불러오기 오류 (화면 나머지는 그대로 둔다)
  const [busy, setBusy] = useState(false); // 더 보기 중
  const latest = useRef(0); // 늦게 도착한 이전 응답을 버리는 요청 번호

  const loadFirst = useCallback(async () => {
    const request = ++latest.current;
    try {
      const result = await apiList<EmailLog>(`/purchase-orders/${orderId}/email-log?page=1&page_size=20`);
      if (request !== latest.current) return;
      setRows(result.data); setMeta(result.meta); setError(null);
    } catch (e) {
      if (request === latest.current) setError(e);
    }
  }, [orderId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    loadFirst(); // 처음 열 때와 발송 직후
  }, [loadFirst, refreshKey]);

  async function loadMore() {
    if (busy || !rows || !meta) return; // 연속 클릭은 한 번만
    setBusy(true);
    const request = latest.current;
    try {
      const result = await apiList<EmailLog>(`/purchase-orders/${orderId}/email-log?page=${meta.page + 1}&page_size=20`);
      if (request !== latest.current) return; // 그사이 새로 불러왔으면 버린다
      const seen = new Set(rows.map((r) => r.id)); // 새 이력이 쌓여 밀린 행이 겹치면 한 번만
      setRows([...rows, ...result.data.filter((r) => !seen.has(r.id))]); setMeta(result.meta); setError(null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const remaining = rows && meta ? Math.max(meta.total - rows.length, 0) : 0;
  return (
    <section aria-labelledby="email-log-heading" style={{ marginTop: "var(--space-lg)" }}>
      <h2 id="email-log-heading">메일 발송 이력</h2>
      <ErrorText error={error} />
      {rows && rows.length === 0 && !error && <p style={S.hint}>발송 이력이 없습니다</p>}
      {rows && rows.length > 0 && (
        <ul role="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {rows.map((r) => (
            <li key={r.id} style={{ ...S.sectionCard, marginTop: "var(--space-sm)" }}>
              <strong>{kindLabel(r.kind)}</strong>{" "}
              <span style={S.hint}>{fmtTime(r.created_at)} · {r.sent_by_name || "알 수 없음"}</span>
              <div>받는 주소: {r.to_address}</div>
              <div>결과: {resultText(r)}</div>
            </li>
          ))}
        </ul>
      )}
      {remaining > 0 && <button type="button" disabled={busy} onClick={loadMore}>{busy ? "불러오는 중…" : `이전 발송 더 보기 (${remaining.toLocaleString("ko-KR")}건 남음)`}</button>}
    </section>
  );
}
