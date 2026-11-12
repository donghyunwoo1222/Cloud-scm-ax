"use client"; // 더 보기 버튼·펼침 상태를 다루므로 브라우저에서 실행

import { useCallback, useEffect, useRef, useState } from "react"; // 상태, 요청 번호 보관

import { apiList, Meta } from "../../../lib/api"; // 목록 호출 (data + meta)
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { ChangeLog, fmtTime, PO_LABELS, PoStatus, STATUS_LABEL } from "../../../lib/po"; // 이력 모양, 시각, 기존 상태·칸 이름 표
import { S } from "../../../lib/styles"; // 화면 공통 스타일

const PREVIEW_LINES = 6; // 한 묶음이 이보다 길면 앞 5줄만 보여 준다
const ITEM_FIELD_LABELS: Record<string, string> = {
  quantity: "수량", unit_price: "단가", min_order_units: "최소 주문 수량", units_per_box: "박스 입수", box_unit_price: "박스 단가", order_unit: "발주단위",
}; // 줄 안의 칸 이름 (모르는 칸은 서버 이름 그대로)

// 값 → 화면 글자. 비었으면 "없음", 상태 코드는 기존 상태 이름 표로 바꾼다 (예: "ORDERED" → "발주함")
const show = (field: string, value: string | null) =>
  value === null || value === "" ? "없음" : field === "status" ? STATUS_LABEL[value as PoStatus] ?? value : value;

// 이력 한 행을 한 줄 문장으로. 모르는 field 는 원래 이름을 그대로 쓴다
// 예) items[A-1].unit_price 1000→1200 → "품목 A-1 단가: 1000 → 1200", due_date 없음 → "약속 납기: 없음 → 2026-11-20"
export function describeChange(row: Pick<ChangeLog, "field" | "old_value" | "new_value">): string {
  const { field, old_value: before, new_value: after } = row;
  const match = /^items\[(.+?)\](?:\.(\w+))?$/.exec(field); // items[SKU] 또는 items[SKU].칸
  if (match && !match[2]) {
    if (before === null) return `품목 ${match[1]} 줄 추가: ${show(field, after)}`;
    if (after === null) return `품목 ${match[1]} 줄 삭제 (${show(field, before)})`;
    return `품목 ${match[1]} 줄: ${show(field, before)} → ${show(field, after)}`;
  }
  const label = match ? `품목 ${match[1]} ${ITEM_FIELD_LABELS[match[2]] ?? match[2]}` : field === "status" ? "상태" : (PO_LABELS as Record<string, string>)[field] ?? field;
  return `${label}: ${show(field, before)} → ${show(field, after)}`;
}

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
  const title = rows.every((r) => r.field === "status") ? "상태 변경" : "수정";
  return (
    <li style={{ ...S.sectionCard, marginTop: "var(--space-sm)" }}>
      <strong>{rows[0].changed_by_name || "알 수 없음"}</strong>{" "}
      <span style={S.hint}>{fmtTime(rows[0].created_at)} · {title}</span>
      <ul style={{ margin: "var(--space-xs) 0 0", paddingLeft: "1.2em" }}>
        {shown.map((r) => (
          <li key={r.id}>
            {describeChange(r)}
            {r.reason && <div style={S.hint}>사유: {r.reason}</div>}
          </li>
        ))}
      </ul>
      {long && <button type="button" onClick={() => setOpen(!open)}>{open ? "접기" : `${rows.length - shown.length}줄 더 보기`}</button>}
    </li>
  );
}

// 발주서 변경 이력 섹션 (최신순, 20건씩 더 보기). refreshKey 가 바뀌면 처음부터 다시 불러온다
export function ChangeLogSection({ orderId, refreshKey }: { orderId: string; refreshKey: number }) {
  const [rows, setRows] = useState<ChangeLog[] | null>(null); // 불러온 행 (null = 아직)
  const [meta, setMeta] = useState<Meta | null>(null); // 마지막으로 받은 쪽 정보
  const [error, setError] = useState<unknown>(null); // 이력 불러오기 오류 (발주서 화면은 그대로 둔다)
  const [busy, setBusy] = useState(false); // 더 보기 중
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
  return (
    <section aria-labelledby="change-log-heading" style={{ marginTop: "var(--space-lg)" }}>
      <h2 id="change-log-heading">변경 이력</h2>
      <ErrorText error={error} />
      {rows && rows.length === 0 && !error && (
        <p style={S.hint}>이력이 없습니다. 이 기능 이전에 만든 발주서는 과거 변경이 기록되어 있지 않을 수 있습니다.</p>
      )}
      {rows && rows.length > 0 && (
        <ul role="list" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {groupRows(rows).map((g) => <Group key={g[0].id} rows={g} />)}
        </ul>
      )}
      {remaining > 0 && <button type="button" disabled={busy} onClick={loadMore}>{busy ? "불러오는 중…" : `이전 이력 더 보기 (${remaining.toLocaleString("ko-KR")}건 남음)`}</button>}
    </section>
  );
}
