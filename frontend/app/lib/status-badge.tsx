// 상태 배지: 색 + 글자 + SVG 아이콘을 항상 같이 보인다 (색만으로 구분하지 않기, MASTER.md).
// 아이콘은 라이브러리 없이 인라인 SVG 로 그린다. 장식이라 aria-hidden (뜻은 옆의 글자가 전한다).
import type { ReactNode } from "react"; // 배지 안 글자 타입

import { S } from "./styles"; // 배지 색·모양

export type BadgeKind = "danger" | "ok" | "unknown" | "info"; // 부족·품절 위험 / 정상 / 판단 불가 / 발주 필요

// 종류별 스타일 (색은 globals.css 토큰)
const STYLE = { danger: S.badgeDanger, ok: S.badgeOk, unknown: S.badgeUnknown, info: S.badgeInfo };

// 종류별 아이콘 모양 (24×24 선 그림): 느낌표 원 / 체크 / 물음표 원 / 시계
const ICON: Record<BadgeKind, ReactNode> = {
  danger: <><circle cx="12" cy="12" r="9" /><line x1="12" y1="7.5" x2="12" y2="12.5" /><line x1="12" y1="16.5" x2="12.01" y2="16.5" /></>,
  ok: <polyline points="5 12.5 10 17 19 7.5" />,
  unknown: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.4" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
  info: <><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" /></>,
};

// 재고 상태 코드(백엔드 SHORTAGE·NORMAL·UNKNOWN) → 배지 종류와 글자
export const STOCK_BADGE = {
  SHORTAGE: { kind: "danger", label: "부족" },
  NORMAL: { kind: "ok", label: "정상" },
  UNKNOWN: { kind: "unknown", label: "판단 불가" },
} as const;

// 배지 한 개. 예: <StatusBadge kind="danger">부족</StatusBadge>
export function StatusBadge({ kind, children }: { kind: BadgeKind; children: ReactNode }) {
  return (
    <span style={STYLE[kind]}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {ICON[kind]}
      </svg>
      {children}
    </span>
  );
}
