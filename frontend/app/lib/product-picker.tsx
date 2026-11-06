"use client";

import { KeyboardEvent, useEffect, useId, useRef, useState } from "react";

import { ErrorText, Pager, useList } from "./list";
import { S } from "./styles";

export type ProductOption = {
  id: number; sku: string; name: string; unit: string; unit_cost: number;
  is_active: boolean; units_per_box?: number | null; box_unit_cost?: number | null;
};

export function ProductPicker({ label, value, onSelect, includeInactive = false, disabled = false }: {
  label: string;
  value?: ProductOption;
  onSelect: (product: ProductOption) => void;
  includeInactive?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null); // 검색 중인 글자와 실제 선택한 품목을 구분한다
  const [active, setActive] = useState(-1);
  const visible = open && !disabled;
  const list = useList<ProductOption>("/products", { include_inactive: includeInactive ? "true" : "", page_size: "6" }, visible);
  const { q, search } = list;
  const term = query?.trim() ?? "";
  const ready = list.isCurrent && term === q;
  const rows = ready && !list.error ? list.rows : [];

  useEffect(() => {
    if (!visible || term === q) return;
    const timer = setTimeout(() => search(term), 300); // 입력이 멈추면 서버에서 전체 품목을 검색한다
    return () => clearTimeout(timer);
  }, [q, search, term, visible]);

  function choose(product: ProductOption) {
    onSelect(product);
    setQuery(null);
    setActive(-1);
    input.current?.setCustomValidity("");
    input.current?.focus();
    setOpen(false);
  }

  function handleKey(event: KeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return; // 한글 조합 중에는 후보를 확정하지 않는다
    if (event.key === "Escape" && (visible || query !== null)) {
      event.preventDefault();
      setQuery(null);
      setActive(-1);
      event.currentTarget.setCustomValidity("");
      setOpen(false);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const next = event.key === "ArrowDown" ? Math.min(active + 1, rows.length - 1) : active < 0 ? rows.length - 1 : active - 1;
      setActive(next);
    } else if (event.key === "Enter" && visible) {
      event.preventDefault(); // 검색 중에는 등록 폼을 제출하지 않는다
      const option = rows[active] ?? (list.meta?.total === 1 ? rows[0] : undefined);
      if (option) choose(option);
      else if (term !== q) search(term);
    }
  }

  const listId = `${id}-options`;
  const optionId = (product: ProductOption) => `${id}-${product.id}`;
  return (
    <div onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) {
        setOpen(false);
        setActive(-1);
      }
    }}>
      <input ref={input} type="text" role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={visible}
        aria-controls={visible ? listId : undefined} aria-activedescendant={visible && rows[active] ? optionId(rows[active]) : undefined}
        placeholder="품목명·SKU 검색" autoComplete="off" maxLength={100} required disabled={disabled}
        style={S.blockFull} value={query ?? (value ? `${value.sku} · ${value.name}` : "")}
        onFocus={(event) => { setOpen(true); if (query === null) event.currentTarget.select(); }}
        onClick={() => setOpen(true)} onKeyDown={handleKey}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(-1);
          // 검색어만 고친 상태에서 이전 품목으로 등록되는 것을 막는다.
          event.currentTarget.setCustomValidity("검색 결과에서 품목을 선택하세요.");
        }} />
      {visible && (
        <>
          <ErrorText error={ready ? list.error : null} />
          <div id={listId} role="listbox" aria-label="품목 검색 결과" aria-busy={!ready}
            style={{ display: "grid", gap: "var(--space-xs)", marginTop: "var(--space-xs)" }}>
            {rows.map((product, index) => (
              <button key={product.id} id={optionId(product)} type="button" role="option" tabIndex={-1}
                aria-selected={index === active} style={{ textAlign: "left", ...(index === active ? S.selectedRow : {}) }}
                onMouseDown={(event) => event.preventDefault()} onClick={() => choose(product)}>
                {product.name}<span style={S.sub}>{product.sku}{product.is_active ? "" : " · 비활성"}</span>
              </button>
            ))}
          </div>
          <p role="status" style={S.hint}>{!ready ? "품목을 찾는 중…" : list.error ? "" : rows.length ? `검색 결과 ${list.meta?.total ?? rows.length}개` : "조건에 맞는 품목이 없습니다."}</p>
          {ready && !list.error && list.meta && list.meta.total > list.meta.page_size && (
            <Pager meta={list.meta} onPage={(page) => { setActive(-1); list.setPage(page); }} />
          )}
        </>
      )}
    </div>
  );
}
