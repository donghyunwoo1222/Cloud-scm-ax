"use client";

import { KeyboardEvent, useEffect, useId, useLayoutEffect, useRef, useState } from "react";

import { ErrorText, Pager, useList } from "./list";
import { skuWithOptions } from "./options";
import { S } from "./styles";

export type ProductOption = {
  id: number; sku: string; name: string; unit: string; unit_cost: number;
  color?: string | null; size?: string | null; spec?: string | null; // 품목 옵션
  is_active: boolean; units_per_box?: number | null; box_unit_cost?: number | null;
  order_unit?: string; // 발주단위 이름 (박스 설정이 없으면 재고 단위)
  min_order_units?: number | null; // 최소 주문량(발주단위 수, #194)
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
  const menu = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState<string | null>(null); // 검색 중인 글자와 실제 선택한 품목을 구분한다
  const [active, setActive] = useState(-1);
  const visible = open && !disabled;
  const list = useList<ProductOption>("/products", { include_inactive: includeInactive ? "true" : "", page_size: "6" }, visible);
  const { q, search } = list;
  const term = query?.trim() ?? "";
  const ready = list.isCurrent && term === q;
  const rows = ready && !list.error ? list.rows : [];

  useLayoutEffect(() => {
    const field = input.current;
    const popup = menu.current;
    if (!visible || !field || !popup) return;

    const position = () => {
      const rect = field.getBoundingClientRect();
      const viewport = window.visualViewport;
      const left = viewport?.offsetLeft ?? 0;
      const top = viewport?.offsetTop ?? 0;
      const right = left + (viewport?.width ?? document.documentElement.clientWidth);
      const bottom = top + (viewport?.height ?? window.innerHeight);
      const width = Math.min(Math.max(rect.width, 240), right - left - 16);
      const below = bottom - rect.bottom - 14;
      const above = rect.top - top - 14;
      const opensAbove = below < 340 && above > below;

      // 화면 끝에 가까우면 위로 펼치고, 발주 표를 가로로 스크롤해도 입력칸을 따라간다.
      popup.style.width = `${width}px`;
      popup.style.left = `${Math.max(left + 8, Math.min(rect.left, right - width - 8))}px`;
      popup.style.top = opensAbove ? "auto" : `${rect.bottom + 6}px`;
      popup.style.bottom = opensAbove ? `${window.innerHeight - rect.top + 6}px` : "auto";
      popup.style.maxHeight = `${Math.max(0, Math.min(340, opensAbove ? above : below))}px`;
    };

    position();
    // 상단 레이어에 띄워 발주 표의 스크롤 영역에 후보가 잘리지 않게 한다.
    popup.showPopover();
    window.addEventListener("scroll", position, true);
    window.addEventListener("resize", position);
    window.visualViewport?.addEventListener("resize", position);
    window.visualViewport?.addEventListener("scroll", position);
    return () => {
      if (popup.matches(":popover-open")) popup.hidePopover();
      window.removeEventListener("scroll", position, true);
      window.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("resize", position);
      window.visualViewport?.removeEventListener("scroll", position);
    };
  }, [visible]);

  const activeId = visible && rows[active] ? `${id}-${rows[active].id}` : undefined;
  useEffect(() => {
    if (activeId) document.getElementById(activeId)?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activeId]);

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
  const hasPages = ready && !list.error && list.meta && list.meta.total > list.meta.page_size;
  return (
    <div className="product-picker" onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) {
        setOpen(false);
        setActive(-1);
      }
    }}>
      <input ref={input} type="text" role="combobox" aria-label={label} aria-autocomplete="list" aria-expanded={visible}
        aria-controls={visible ? listId : undefined} aria-activedescendant={activeId}
        placeholder="품목명·SKU·옵션 검색" autoComplete="off" maxLength={100} required disabled={disabled}
        style={S.blockFull} value={query ?? (value ? `${value.name} · ${value.sku}` : "")}
        onFocus={(event) => { setOpen(true); if (query === null) event.currentTarget.select(); }}
        onClick={() => setOpen(true)} onKeyDown={handleKey}
        onChange={(event) => {
          setQuery(event.target.value);
          setOpen(true);
          setActive(-1);
          // 검색어만 고친 상태에서 이전 품목으로 등록되는 것을 막는다.
          event.currentTarget.setCustomValidity("검색 결과에서 품목을 선택하세요.");
        }} />
      <svg className="product-picker-chevron" aria-hidden="true" viewBox="0 0 16 16" fill="none">
        <path d="m4 6 4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {visible && (
        <div ref={menu} className="product-picker-menu" popover="manual">
          <div className="product-picker-options" id={listId} role="listbox" aria-label="품목 검색 결과" aria-busy={!ready}>
            {rows.map((product, index) => (
              <button key={product.id} id={`${id}-${product.id}`} type="button" role="option" tabIndex={-1}
                aria-selected={index === active}
                onMouseDown={(event) => event.preventDefault()} onClick={() => choose(product)}>
                {product.name}<span style={S.sub}>{skuWithOptions(product.sku, product)}{product.is_active ? "" : " · 비활성"}</span>
              </button>
            ))}
          </div>
          <div className="product-picker-footer">
            {hasPages ? (
              <Pager meta={list.meta} onPage={(page) => {
                input.current?.focus();
                setActive(-1);
                list.setPage(page);
              }} />
            ) : (
              <p role="status">{!ready ? "품목을 찾는 중…" : list.error ? "" : rows.length ? `검색 결과 ${list.meta?.total ?? rows.length}개` : "조건에 맞는 품목이 없습니다."}</p>
            )}
            <ErrorText error={ready ? list.error : null} />
          </div>
        </div>
      )}
    </div>
  );
}
