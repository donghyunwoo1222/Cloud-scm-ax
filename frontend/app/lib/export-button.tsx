"use client"; // 상태·클릭을 쓰는 부품이라 브라우저에서 실행

import { ReactNode, useState } from "react"; // 화면에 붙일 안내, 상태

import { apiDownload } from "./api"; // 파일 내려받기
import { ErrorText } from "./list"; // 서버 오류 문장 표시
import { S } from "./styles"; // 화면 공통 스타일
import { useToast } from "./toast"; // 성공 알림

// "내보내기" 버튼 + 작은 패널 (#191). 현재 검색·필터 조건(query)을 그대로 내보내기 경로에 붙인다
// 예) path="/products/export", query="q=컵" → GET /api/v1/products/export?q=컵&format=xlsx
export function ExportButton({ path, query, summary, note }: {
  path: string; // 내보내기 경로 (예: /stock/export)
  query: string; // page·page_size 를 뺀 현재 조건 (없으면 "")
  summary: string | null; // 건수 문구 (목록 meta.total 로 만든다. 예: "품목 12건", 발주서는 "발주서 12건(항목 줄 단위로 내보내요)". 아직 모르면 null)
  note?: ReactNode; // 패널 아래 덧붙일 안내 (품목: 가져오기 안내)
}) {
  const toast = useToast(); // 성공 알림 토스트
  const [open, setOpen] = useState(false); // 패널 열림
  const [format, setFormat] = useState<"xlsx" | "csv">("xlsx"); // 기본은 엑셀
  const [busy, setBusy] = useState(false); // 내려받는 중이면 연속 클릭을 막는다
  const [error, setError] = useState<unknown>(null); // 서버가 준 실패 문장

  async function run() {
    if (busy) return; // 이중 클릭 방어
    setBusy(true);
    setError(null);
    try {
      await apiDownload(`${path}?${query ? `${query}&` : ""}format=${format}`); // 조건 + 형식
      toast("내보냈어요");
      setOpen(false);
    } catch (e) {
      setError(e); // 예: EXPORT_TOO_LARGE 의 "기간이나 조건을 좁혀 주세요"
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "inline-block" }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>내보내기</button>
      {open && (
        <div style={S.panel}>
          <div>
            <p style={{ margin: 0 }}>현재 검색·필터 조건으로 내보냅니다{summary && ` · ${summary}`}</p>
            <fieldset disabled={busy} style={{ border: 0, padding: 0, margin: "8px 0" }}>
              <label><input type="radio" name="export-format" checked={format === "xlsx"} onChange={() => setFormat("xlsx")} /> 엑셀(xlsx)</label>{" "}
              <label><input type="radio" name="export-format" checked={format === "csv"} onChange={() => setFormat("csv")} /> csv</label>
            </fieldset>
            <button type="button" disabled={busy} onClick={run}>{busy ? "내보내는 중…" : "내려받기"}</button>
            {note && <p style={{ ...S.hint, margin: "8px 0 0" }}>{note}</p>}
            <ErrorText error={error} />
          </div>
        </div>
      )}
    </div>
  );
}
