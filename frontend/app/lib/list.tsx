"use client"; // 상태·입력을 다루는 화면 부품이라 브라우저에서 실행

import { FormEvent, useCallback, useEffect, useState } from "react"; // 폼 제출, 함수 기억, 처음·변경 시 실행, 상태

import { apiList, ApiError, Meta } from "./api"; // 목록 API 호출, 서버 오류, 쪽 정보

// 목록 화면 공통 상태: 쪽 번호·검색어·비활성 포함 여부를 바꾸면 서버에서 다시 불러온다 (서버 규칙: 20개씩, 최신순)
export function useList<T>(basePath: string) {
  const [page, setPage] = useState(1); // 지금 쪽 (1부터)
  const [q, setQ] = useState(""); // 적용된 검색어
  const [includeInactive, setIncludeInactive] = useState(false); // 비활성 포함 보기 (기본은 숨김)
  const [rows, setRows] = useState<T[]>([]); // 이 쪽의 행들
  const [meta, setMeta] = useState<Meta | null>(null); // 쪽 정보 (전체 개수 등)
  const [error, setError] = useState<unknown>(null); // 불러오기 오류

  const reload = useCallback(async () => {
    const params = new URLSearchParams({ page: String(page) }); // 쿼리 문자열 만들기 (예: page=2&q=유통)
    if (q) params.set("q", q); // 검색어가 있을 때만
    if (includeInactive) params.set("include_inactive", "true"); // 비활성 포함일 때만
    try {
      const result = await apiList<T>(`${basePath}?${params}`); // 서버에서 한 쪽 가져오기
      setRows(result.data); // 행 바꾸기
      setMeta(result.meta); // 쪽 정보 바꾸기
      setError(null); // 이전 오류 지우기
    } catch (e) {
      setError(e); // 화면에 보여줄 오류
    }
  }, [basePath, page, q, includeInactive]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 목록을 서버에서 불러와 상태에 넣는 것이 이 효과의 목적이다
    reload(); // 처음 열 때와 쪽·검색어·필터가 바뀔 때마다 다시 불러온다
  }, [reload]);

  // 검색어·필터가 바뀌면 1쪽부터 다시 본다
  function search(nextQ: string) {
    setQ(nextQ.trim()); // 앞뒤 공백 제거
    setPage(1);
  }
  function toggleInactive(value: boolean) {
    setIncludeInactive(value);
    setPage(1);
  }

  return { rows, meta, error, page, setPage, includeInactive, search, toggleInactive, reload };
}

// 검색창 + "비활성 포함" 선택
export function ListControls({
  placeholder, // 검색창 안내 문구
  includeInactive, // 지금 비활성 포함 여부
  onSearch, // 검색 실행
  onToggleInactive, // 비활성 포함 바꾸기
}: {
  placeholder: string;
  includeInactive: boolean;
  onSearch: (q: string) => void;
  onToggleInactive: (value: boolean) => void;
}) {
  const [text, setText] = useState(""); // 입력 중인 검색어 (검색 버튼을 눌러야 적용)

  function submit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    onSearch(text); // 검색 적용
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: "0.5rem", alignItems: "center", margin: "1rem 0" }}>
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder={placeholder} aria-label="검색어" />
      <button type="submit">검색</button>
      <label style={{ marginLeft: "1rem" }}>
        <input type="checkbox" checked={includeInactive} onChange={(e) => onToggleInactive(e.target.checked)} /> 비활성 포함
      </label>
    </form>
  );
}

// 쪽 이동: 이전 / "2 / 5쪽 (전체 87개)" / 다음
export function Pager({ meta, onPage }: { meta: Meta | null; onPage: (page: number) => void }) {
  if (!meta) return null; // 아직 불러오기 전
  const last = Math.max(1, Math.ceil(meta.total / meta.page_size)); // 마지막 쪽 (예: 87개, 20개씩 → 5쪽)
  return (
    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginTop: "0.75rem" }}>
      <button type="button" disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)}>
        이전
      </button>
      <span>
        {meta.page} / {last}쪽 (전체 {meta.total}개)
      </span>
      <button type="button" disabled={meta.page >= last} onClick={() => onPage(meta.page + 1)}>
        다음
      </button>
    </div>
  );
}

// 서버 오류를 그대로 보여준다. 입력값 오류면 어느 칸인지(labels 로 한글 이름)도 덧붙인다
export function ErrorText({ error, labels = {} }: { error: unknown; labels?: Record<string, string> }) {
  if (!error) return null; // 오류 없음
  if (!(error instanceof ApiError)) return <p role="alert" style={{ color: "crimson" }}>알 수 없는 오류가 났습니다.</p>;
  const fields = Array.isArray(error.details) // details 가 [{field, reason}, ...] 모양이면
    ? (error.details as { field?: string }[]).map((d) => labels[d.field ?? ""] ?? d.field).filter(Boolean)
    : []; // 칸 이름만 모은다
  return (
    <p role="alert" style={{ color: "crimson" }}>
      {error.message}
      {/* 서버 문장 그대로 (예: "이미 같은 SKU 의 품목이 있습니다.") */}
      {fields.length > 0 && ` (${fields.join(", ")})`}
      {/* 예: "입력값을 확인해 주세요. (리드타임)" */}
    </p>
  );
}
