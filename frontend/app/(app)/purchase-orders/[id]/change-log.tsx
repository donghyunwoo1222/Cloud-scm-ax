"use client"; // 더 보기 버튼·펼침 상태를 다루므로 브라우저에서 실행

import { useCallback, useEffect, useRef, useState } from "react"; // 상태, 요청 번호 보관

import { apiList, Meta } from "../../../lib/api"; // 목록 호출 (data + meta)
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { describeChangeParts } from "../../../lib/change-describe"; // 이력 한 행의 문장·항목/이전/이후 (시험하려고 lib 로 분리)
import { ChangeLog, fmtTime } from "../../../lib/po"; // 이력 모양, 시각

const SHOWN_GROUPS = 3; // 처음에는 최근 3묶음만 보인다
const PREVIEW_LINES = 6; // 한 묶음이 이보다 길면 앞 5줄만 보여 준다
// 같은 시각(created_at 글자 그대로)·같은 사람(이름)의 연속된 행을 한 묶음으로 만든다. 한 번의 저장은 시각이 같다
function groupRows(rows: ChangeLog[]): ChangeLog[][] {
  const groups: ChangeLog[][] = [];
  for (const row of rows) {
    const last = groups[groups.length - 1];
    if (last && last[0].created_at === row.created_at && last[0].changed_by_name === row.changed_by_name) last.push(row); // 같은 묶음
    else groups.push([row]); // 새 묶음
  }
  return groups;
}

function Group({ rows }: { rows: ChangeLog[] }) {
  const [open, setOpen] = useState(false); // 긴 묶음을 펼쳤는지
  const long = rows.length > PREVIEW_LINES;
  const shown = long && !open ? rows.slice(0, PREVIEW_LINES - 1) : rows; // 6줄을 넘으면 5줄만
  const title = rows.every((r) => r.field === "status") ? "상태 변경" : rows.every((r) => r.field.startsWith("supplier_")) ? "공급업체 회신" : "수정"; // 링크·직원 입력은 이름으로 구분한다
  // 잔량 마감 = 같은 묶음에 items[SKU].closed_quantity 행이 있다 (서버가 마감 때만 같이 남긴다). 사유는 상태 줄에만 보이게 한다
  // shortcut: 20건 쪽 경계에서 묶음이 갈리면 "(잔량 마감)" 표시가 빠질 수 있다, 이력 데이터에 마감 표시가 생기면 그걸 쓴다
  const isClose = rows.some((r) => /\.closed_quantity$/.test(r.field));
  return (
    <li className="cl-card">
      <div className="cl-head">
        <strong>{rows[0].changed_by_name || "알 수 없음"}</strong>
        <span className="cl-time">{fmtTime(rows[0].created_at)}</span>
        <span className="cl-badge">{title}</span>
      </div>
      <ul className="cl-rows" role="list">
        {shown.map((r) => {
          const p = describeChangeParts(r);
          return (
            <li key={r.id} className="cl-row">
              <span className="cl-label">{p.label}</span>
              <span className="cl-values">
                {p.before === null ? <span className="cl-none">(없음)</span> : <span className="cl-before">{p.before}</span>}
                <span className="cl-arrow" aria-label="에서">→</span>
                {p.after === null ? <span className="cl-none">(없음)</span> : <strong className="cl-after">{p.after}</strong>}
                {isClose && r.field === "status" && r.new_value === "RECEIVED" && <span className="cl-before"> (잔량 마감)</span>}
              </span>
              {r.reason && !r.field.endsWith(".closed_quantity") && <span className="cl-reason">사유: {r.reason}</span>}
            </li>
          );
        })}
      </ul>
      {long && <button type="button" onClick={() => setOpen(!open)}>{open ? "접기" : `${rows.length - shown.length}줄 더 보기`}</button>}
    </li>
  );
}

// 발주서 변경 이력 구역 ("기록" 카드 안, 최신순, 20건씩 더 보기). refreshKey 가 바뀌면 처음부터 다시 불러온다
export function ChangeLogSection({ orderId, refreshKey }: { orderId: string; refreshKey: number }) {
  const [rows, setRows] = useState<ChangeLog[] | null>(null); // 불러온 행 (null = 아직)
  const [meta, setMeta] = useState<Meta | null>(null); // 마지막으로 받은 쪽 정보
  const [error, setError] = useState<unknown>(null); // 이력 불러오기 오류 (발주서 화면은 그대로 둔다)
  const [busy, setBusy] = useState(false); // 더 보기 중
  const [expanded, setExpanded] = useState(false); // 4묶음 이상일 때 전부 펼쳤는지
  const latest = useRef(0); // 늦게 도착한 이전 응답을 버리는 요청 번호

  const loadFirst = useCallback(async () => {
    const request = ++latest.current;
    try {
      const result = await apiList<ChangeLog>(`/purchase-orders/${orderId}/change-log?page=1&page_size=20`);
      if (request !== latest.current) return;
      setRows(result.data); setMeta(result.meta); setError(null);
    } catch (e) {
      if (request === latest.current) setError(e);
    }
  }, [orderId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    loadFirst(); // 처음 열 때와 발주서가 바뀐 뒤
  }, [loadFirst, refreshKey]);

  async function loadMore() {
    if (busy || !rows || !meta) return; // 연속 클릭은 한 번만
    setBusy(true);
    const request = latest.current;
    try {
      const result = await apiList<ChangeLog>(`/purchase-orders/${orderId}/change-log?page=${meta.page + 1}&page_size=20`);
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
  const groups = rows ? groupRows(rows) : [];
  const collapsible = groups.length > SHOWN_GROUPS; // 4묶음 이상일 때만 더 보기/접기
  if (!error && groups.length === 0) return null; // 항목이 없으면 빈 틀을 그리지 않는다
  return (
    <div className="rec-zone" aria-labelledby="change-log-heading">
      <h3 id="change-log-heading">변경 이력</h3>
      <ErrorText error={error} />
      {groups.length > 0 && (
        <ul role="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {(collapsible && !expanded ? groups.slice(0, SHOWN_GROUPS) : groups).map((g) => <Group key={g[0].id} rows={g} />)}
        </ul>
      )}
      {collapsible && <button type="button" onClick={() => setExpanded(!expanded)}>{expanded ? "접기" : `더 보기 (${groups.length - SHOWN_GROUPS}묶음)`}</button>}
      {remaining > 0 && (!collapsible || expanded) && <button type="button" disabled={busy} onClick={loadMore}>{busy ? "불러오는 중…" : `이전 이력 더 보기 (${remaining.toLocaleString("ko-KR")}건 남음)`}</button>}
    </div>
  );
}
