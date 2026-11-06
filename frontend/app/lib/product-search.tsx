"use client"; // 여러 폼에서 같은 서버 검색과 쪽 나누기를 쓴다.

import { useEffect, useState } from "react"; // 검색어를 입력하는 동안 요청을 잠시 미룬다.
import { ErrorText, Pager, useList } from "./list"; // 기존 목록 조회·오류·쪽 이동

export type ProductOption = {
  id: number; sku: string; name: string; unit: string; unit_cost: number;
  is_active: boolean; units_per_box?: number | null; box_unit_cost?: number | null;
};

export function useProductOptions(includeInactive = false) {
  return useList<ProductOption>("/products", { include_inactive: includeInactive ? "true" : "" });
}

export function ProductSearch({ list, label = "품목명·SKU 검색" }: {
  list: ReturnType<typeof useProductOptions>; label?: string;
}) {
  const [text, setText] = useState(""); // 검색창에는 입력값을 즉시 보여준다.
  const { q, search } = list;
  useEffect(() => {
    if (text.trim() === q) return; // 같은 조건을 중복 요청하지 않는다.
    const timer = setTimeout(() => search(text), 300); // 입력이 멈추면 전체 품목에서 검색한다.
    return () => clearTimeout(timer);
  }, [text, q, search]);
  const ready = list.isCurrent && text.trim() === q;

  return (
    <div style={S.search}>
      <label>{label}<input type="search" maxLength={100} value={text} onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Enter" || event.nativeEvent.isComposing) return; // 한글 조합은 브라우저에 맡긴다.
          event.preventDefault(); // 검색창 Enter로 부모 등록 폼을 제출하지 않는다.
          search(text);
        }} /></label>
      <ErrorText error={list.error} />
      <p role="status">{!ready ? "품목을 찾는 중…" : !list.error && list.meta?.total === 0 ? "조건에 맞는 품목이 없습니다." : ""}</p>
      {ready && !list.error && list.meta && list.meta.total > list.meta.page_size && <Pager meta={list.meta} onPage={list.setPage} />}
    </div>
  );
}

const S = { search: { marginBlock: "var(--space-md)", maxWidth: "24rem" } }; // 검색과 쪽 이동을 선택 상자 가까이에 둔다.
