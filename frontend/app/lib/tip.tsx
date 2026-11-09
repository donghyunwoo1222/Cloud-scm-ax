"use client"; // 마우스·포커스 이벤트와 popover 를 쓰는 부품이라 브라우저에서 실행

import { ReactNode, useId, useRef } from "react"; // 말풍선 연결 번호, 위치 계산용 ref

// 말풍선: 마우스를 올리거나 누르거나(터치) Tab 으로 오면 열린다. 글자를 줄글로 깔지 않고 필요할 때만 보여 준다.
// 표 상자의 가로 스크롤에 잘리지 않게 popover(맨 위 층)로 띄우고 트리거 바로 아래에 둔다. 설명이 없으면 트리거만 그린다.
// 예) <Tip detail="가용재고 0개 · 재주문점 16개"><StatusBadge …>부족</StatusBadge></Tip>
export function Tip({ detail, label, id, children }: { detail?: string; label?: string; id?: string; children: ReactNode }) {
  const own = useId(); // id 를 따로 주지 않으면 자동 번호
  const tipId = id ?? own; // 입력칸의 aria-describedby 가 가리킬 수 있게 밖에서 정할 수도 있다
  const button = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLSpanElement>(null);
  if (!detail) return <>{children}</>;
  const hide = () => { if (tip.current?.matches(":popover-open")) tip.current.hidePopover(); };
  const show = () => {
    const t = tip.current, rect = button.current?.getBoundingClientRect();
    if (!t || !rect) return;
    t.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 248))}px`; // 말풍선 폭 240px + 여백 8px 이 화면 밖으로 나가지 않게
    t.style.top = `${rect.bottom + 4}px`;
    if (!t.matches(":popover-open")) t.showPopover();
    window.addEventListener("scroll", hide, { capture: true, once: true }); // 위치가 고정이라 스크롤하면 닫는다
  };
  return (
    <>
      <button ref={button} type="button" className="status-tip" aria-label={label} aria-describedby={tipId}
        onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} onClick={show}>{children}</button>
      <span ref={tip} id={tipId} role="tooltip" popover="auto" className="status-tip-text">{detail}</span>
    </>
  );
}

// 작은 "i" 아이콘 말풍선: 입력칸 옆 보조 설명용. 예) <InfoTip detail="발주 후 입고까지 걸리는 기간" />
export function InfoTip({ detail, label = "자세히 보기", id }: { detail: string; label?: string; id?: string }) {
  return (
    <Tip detail={detail} label={label} id={id}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ color: "var(--color-muted-foreground)", verticalAlign: "-3px" }}>
        <circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-8h.01" />
      </svg>
    </Tip>
  );
}
