// 상태 배지: 색 + 글자 + SVG 아이콘을 항상 같이 보인다 (색만으로 구분하지 않기, MASTER.md).
// 아이콘은 라이브러리 없이 인라인 SVG 로 그린다. 장식이라 aria-hidden (뜻은 옆의 글자가 전한다).
import type { ReactNode } from "react"; // 배지 안 글자 타입

import { type PoStatus, STATUS_LABEL } from "./po"; // 발주 목록과 같은 상태 이름을 쓴다
import { S } from "./styles"; // 배지 색·모양

export type BadgeKind = "danger" | "ok" | "unknown" | "info"; // 부족·품절 위험 / 정상 / 판단 불가 / 발주 필요

// 종류별 스타일 (색은 globals.css 토큰)
const STYLE = { danger: S.badgeDanger, ok: S.badgeOk, unknown: S.badgeUnknown, info: S.badgeInfo };

// 종류별 아이콘 모양 (24×24 선 그림): 느낌표 원 / 체크 / 물음표 원 / 시계
const ICON = {
  danger: <><circle cx="12" cy="12" r="9" /><line x1="12" y1="7.5" x2="12" y2="12.5" /><line x1="12" y1="16.5" x2="12.01" y2="16.5" /></>,
  ok: <polyline points="5 12.5 10 17 19 7.5" />,
  unknown: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.4" /><line x1="12" y1="17" x2="12.01" y2="17" /></>,
  info: <><circle cx="12" cy="12" r="9" /><polyline points="12 7 12 12 15 14" /></>,
  draft: <><path d="M5 19l1-4 9-9 3 3-9 9z" /><path d="M13.5 7.5l3 3" /></>, // 작성 중은 연필 모양으로 표시한다
  cancelled: <><circle cx="12" cy="12" r="9" /><path d="m9 9 6 6m0-6-6 6" /></>, // 취소는 원 안의 X로 표시한다
  sale: <><path d="M5 8h14l1 12H4L5 8Z" /><path d="M9 9V7a3 3 0 0 1 6 0v2" /></>,
  outbound: <path d="M4 12h15m-6-6 6 6-6 6" />,
  adjustment: <path d="M4 7h16M8 4v6m-4 7h16m-4-3v6" />,
};

// 재고 상태 코드(백엔드 SHORTAGE·NORMAL·UNKNOWN) → 배지 종류와 글자
export const STOCK_BADGE = {
  SHORTAGE: { kind: "danger", label: "부족" },
  NORMAL: { kind: "ok", label: "정상" },
  UNKNOWN: { kind: "unknown", label: "판단 불가" },
} as const;

// 배지 한 개. 예: <StatusBadge kind="danger">부족</StatusBadge>
export function StatusBadge({ kind, children, icon = kind }: { kind: BadgeKind; children: ReactNode; icon?: keyof typeof ICON }) { // 같은 색 계열에 다른 의미의 아이콘을 쓸 수 있다
  return (
    <span style={STYLE[kind]}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        {ICON[icon]}{/* 지정한 장식 아이콘을 그린다 */}
      </svg>
      {children}
    </span>
  );
}

const PO_BADGE: Record<PoStatus, { kind: BadgeKind; icon?: keyof typeof ICON }> = { // 발주 상태 다섯 가지를 기존 색 토큰에 연결한다
  DRAFT: { kind: "unknown", icon: "draft" }, // 작성 중은 중립색과 연필
  APPROVED: { kind: "info", icon: "ok" }, // 승인됨은 정보색과 체크
  ORDERED: { kind: "info" }, // 발주함은 입고를 기다리므로 정보색과 시계
  RECEIVED: { kind: "ok" }, // 입고 완료는 완료색과 체크
  CANCELLED: { kind: "unknown", icon: "cancelled" }, // 취소는 중립색과 X
};

export function PurchaseOrderStatusBadge({ status }: { status: PoStatus }) { // 발주 상세와 목록이 같은 상태 배지를 쓸 수 있다
  return <StatusBadge {...PO_BADGE[status]}>{STATUS_LABEL[status]}</StatusBadge>; // 공통 상태 이름을 항상 글자로 보여준다
}

const SHIPMENT_BADGE: Partial<Record<string, { kind: BadgeKind; icon: keyof typeof ICON }>> = {
  SALE: { kind: "unknown", icon: "sale" },
  DISPOSAL: { kind: "danger", icon: "cancelled" },
  OTHER_OUT: { kind: "unknown", icon: "outbound" },
  ADJUSTMENT: { kind: "info", icon: "adjustment" },
};

export function ShipmentTypeBadge({ type, children }: { type: string; children: ReactNode }) {
  const badge = SHIPMENT_BADGE[type];
  return badge ? <StatusBadge {...badge}>{children}</StatusBadge> : children;
}
