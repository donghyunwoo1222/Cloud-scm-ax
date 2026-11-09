// 화면 공통 스타일 모음. 인라인 style 을 화면마다 따로 쓰지 않고 여기서 가져다 쓴다.
// 색·간격·글자 크기는 globals.css 의 토큰(var(--…))만 쓴다. 규칙의 기준은 design-system/cloud-scm/MASTER.md.
// 버튼·입력칸·표 칸·제목의 기본 모양은 globals.css 가 태그 단위로 입힌다(화면마다 style 을 달지 않아도 된다).
import type { CSSProperties } from "react"; // 인라인 스타일 객체의 타입

// 상태 배지의 공통 틀 (색은 아래 badge* 에서 고른다). 배지에는 항상 글자를 넣는다(색만으로 구분하지 않기)
const badgeBase: CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: "var(--space-xs)", padding: "2px var(--space-sm)",
  borderRadius: "var(--radius-full)", fontSize: "var(--text-xs)", fontWeight: 500, whiteSpace: "nowrap",
};

// 입력 항목 줄: 항목 사이 16px, 위쪽 기준 정렬(한 항목 아래에 "현재고 N개" 가 생겨도 옆 라벨이 밀리지 않는다), 넘치면 다음 줄로
const fieldRow: CSSProperties = { display: "flex", flexWrap: "wrap", gap: "var(--field-row-gap) var(--field-gap)", alignItems: "flex-start", margin: "var(--field-gap) 0" };

// 여러 화면이 같이 쓰는 스타일 이름 → 값
export const S = {
  // 레이아웃 (로그인 후 화면: 왼쪽 사이드 메뉴 + 오른쪽 상단 바·본문)
  shell: { display: "flex", flexWrap: "wrap", flex: 1 }, // 메뉴와 본문을 가로로. 좁은 화면에서는 메뉴가 위로 쌓인다
  sidebar: { background: "var(--color-card)", borderRight: "1px solid var(--color-border)" }, // 사이드 메뉴 상자 (폭·여백·고정은 화면 폭마다 달라 globals.css 의 .sidebar)
  sideNav: { display: "flex", flexDirection: "column", gap: 2 }, // 메뉴 링크 세로 나열 (모양은 globals.css 의 .side-nav)
  navGroupTitle: { margin: 0, padding: "var(--space-md) 12px var(--space-xs)", fontSize: "var(--text-xs)", fontWeight: 600, color: "var(--color-muted-foreground)" }, // 메뉴 그룹 제목 (예: 재고 업무). 링크보다 작고 흐리게 해 눌리는 메뉴와 구분
  content: { flex: "999 1 560px", minWidth: 0, display: "flex", flexDirection: "column" }, // 메뉴 오른쪽 전체 (표가 넓어도 화면 밖으로 밀지 않게 minWidth 0)
  topbar: { display: "flex", flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center", gap: "var(--space-md)", padding: "12px var(--space-lg)", background: "var(--color-card)", borderBottom: "1px solid var(--color-border)", fontSize: "var(--text-sm)", color: "var(--color-muted-foreground)" }, // 상단 바: 내 정보·로그아웃
  main: { padding: "var(--page-pad)", maxWidth: 1360, width: "100%" }, // 본문 여백 (display 를 주지 않는다: hidden 속성이 먹어야 한다)
  pad2: { padding: "var(--space-xl)" }, // 안내 문구 여백
  loginPage: { background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-xl)", width: "calc(100% - 2 * var(--space-md))", maxWidth: 380, margin: "10vh auto 0" }, // 로그인 화면 틀: 가운데 흰 카드

  // 카드·제목·안내
  card: { background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--card-pad)" }, // 흰 카드 상자
  sectionCard: { background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--card-pad)", marginTop: "var(--space-md)" }, // 화면 안에서 항목마다 쌓는 흰 카드 (대시보드)
  sectionTitle: { marginTop: "var(--section-gap)" }, // 화면 안의 두 번째 제목
  detailHeader: { display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "var(--space-sm)", marginBottom: "var(--space-md)" }, // 상세 제목과 목록 링크를 양쪽에 두고 좁으면 줄바꿈
  detailTitle: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "var(--space-sm)" }, // 발주번호와 상태 배지를 같이 읽도록 배치
  detailFacts: { display: "flex", flexWrap: "wrap", gap: "var(--space-md) var(--space-xl)", margin: 0 }, // 공급업체와 약속 납기를 같은 줄에 두되 좁으면 아래로
  detailLabel: { color: "var(--color-muted-foreground)", fontSize: "var(--text-sm)" }, // 핵심 값 위의 작은 항목 이름
  detailValue: { margin: 0, fontSize: "var(--text-lg)", fontWeight: 700, overflowWrap: "anywhere" }, // 값은 크게 보여주고 긴 업체명도 카드 안에서 줄바꿈
  detailMeta: { marginTop: "var(--space-md)", paddingTop: "var(--space-sm)", borderTop: "1px solid var(--color-border)", color: "var(--color-muted-foreground)", fontSize: "var(--text-sm)", overflowWrap: "anywhere" }, // 기록과 메모를 구분선 아래에 배치
  detailHistory: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 11rem), 1fr))", gap: "var(--space-sm)", margin: 0 }, // 기록을 같은 너비의 칸에 두고 화면이 좁으면 칸을 아래로 보낸다
  detailHistoryCell: { padding: "var(--space-sm) var(--space-md)", borderRadius: "var(--radius-sm)", background: "var(--color-hover)" }, // 연한 배경으로 승인·발주·입고 기록을 구분한다
  detailHistoryValue: { margin: "var(--space-xs) 0 0", color: "var(--color-foreground)", fontWeight: 500 }, // 항목명 아래 날짜나 메모를 본문색으로 강조한다
  detailMemo: { margin: "var(--space-md) 0 0", paddingInline: "var(--space-md)" }, // 메모는 날짜 칸 아래에서 가로 폭 전체를 쓴다
  detailFilterGroup: { display: "flex", flexWrap: "wrap", gap: "var(--space-xs)", padding: "var(--space-xs)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-sm)" }, // 필터 두 버튼을 하나의 테두리 안에 묶는다
  detailFilterButton: { display: "inline-flex", alignItems: "center", gap: "var(--space-xs)", minHeight: "var(--chip-min)", paddingInline: "var(--space-sm)", border: 0, outlineOffset: -2 }, // 체크와 글자를 나란히 두고 키보드 테두리를 버튼 안쪽에 표시한다
  detailFilterSelected: { background: "var(--color-selected)", color: "var(--color-link)", fontWeight: 700 }, // 현재 선택은 배경과 굵은 글자로 강조한다
  detailTableCount: { margin: 0, marginInlineStart: "auto", fontSize: "var(--text-sm)", color: "var(--color-muted-foreground)" }, // 표시 개수는 남는 공간의 오른쪽 끝에 둔다

  // 대시보드 숫자 카드 (#92)
  kpiGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: "var(--space-md)", marginTop: "var(--space-md)" }, // 카드 줄: 칸이 모자라면 다음 줄로 (160px: 768px 화면에서도 3장이 한 줄)
  kpiCard: { display: "flex", flexDirection: "column", gap: "var(--space-xs)", minWidth: 0, background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md)", color: "var(--color-foreground)" }, // 숫자 카드 상자 (링크여도 글자는 본문색, 강조는 hover 테두리)
  kpiLabel: { fontSize: "var(--text-sm)", fontWeight: 500, color: "var(--color-muted-foreground)" }, // 카드 이름
  kpiValue: { fontSize: "var(--text-xl)", fontWeight: 700, fontVariantNumeric: "tabular-nums" }, // 큰 숫자 (자릿수 폭 고정)
  kpiSub: { fontSize: "var(--text-xs)", color: "var(--color-muted-foreground)" }, // 숫자 아래 보조 설명
  kpiMore: { marginTop: "auto", paddingTop: "var(--space-xs)", fontSize: "var(--text-sm)", color: "var(--color-link)" }, // "… 보기" (카드 맨 아래로 밀어 높이가 달라도 줄을 맞춘다)
  hint: { color: "var(--color-muted-foreground)" }, // 화면 설명·보조 글자
  empty: { padding: "var(--space-lg)", textAlign: "center", color: "var(--color-muted-foreground)" }, // 목록이 비었을 때 안내
  error: { color: "var(--color-destructive)" }, // 오류 문장
  ok: { color: "var(--color-ok)" }, // 성공 문장

  // 표
  table: { width: "100%", minWidth: 640, borderCollapse: "collapse" }, // 최소 폭 640px: 이보다 좁으면 칸을 짜부라뜨리지 않고 가로 스크롤 상자 안에서 스크롤된다
  tableWide: { width: "100%", minWidth: 1180, borderCollapse: "collapse" }, // 칸이 12개인 추천 표 등: 최소 폭 1180px // 표: 가로 꽉 채우고 칸 사이 틈 없앰 (칸 모양은 globals.css 의 th·td)
  tableBox: { overflowX: "auto" }, // 표가 화면보다 넓으면 이 상자 안에서만 가로 스크롤
  headRow: { textAlign: "left" }, // 표 머리 줄: 글자 열은 왼쪽 정렬
  row: {}, // 표 본문 줄 (구분선은 globals.css 의 td 가 그린다)
  num: { textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }, // 숫자 칸: 오른쪽 정렬 + 숫자 폭 같게 (머리 칸에도 같이 쓴다)
  dim: { color: "var(--color-muted-foreground)" }, // 덜 중요한 숫자 (계산 재료)
  key: { fontWeight: 700 }, // 판단에 쓰는 핵심 숫자
  numInput: { width: 84, textAlign: "right", fontVariantNumeric: "tabular-nums" }, // 숫자 입력칸 (수량): 오른쪽 정렬
  groupHead: { textAlign: "center", fontSize: "var(--text-xs)", background: "var(--color-hover)" }, // 열 묶음 줄의 칸 ("재고", "판단 기준" 등)
  groupStart: { borderLeft: "1px solid var(--color-border)" }, // 묶음이 시작되는 칸 왼쪽 구분선
  nowrap: { whiteSpace: "nowrap" }, // 칸 글자가 두 줄로 꺾이지 않게 (예: "발주 필요", 날짜)
  midCol: { minWidth: 120 }, // 품목명·업체명 칸의 최소 폭 (이름이 한 글자씩 꺾이지 않게)
  wideCol: { minWidth: 300 }, // 이유 칸의 최소 폭: 한 줄 요약("가용 50 ≤ 재주문점 50 → 140개 추천")과 "자세히"가 한 줄에 들어가는 폭. 펼친 전체 문장은 줄바꿈된다
  sub: { display: "block", fontSize: "var(--text-xs)", color: "var(--color-muted-foreground)", fontWeight: 400, whiteSpace: "nowrap" }, // 칸 안의 보조 글자 (예: 품목 아래 SKU)
  selectedRow: { background: "var(--color-selected)" }, // 체크한 줄
  selectedMark: { boxShadow: "inset 3px 0 0 var(--color-primary)" }, // 체크한 줄의 첫 칸 왼쪽 파란 세로줄

  // 링크를 파란 주요 버튼 모양으로 (예: 발주서 작성). 화면 이동은 링크라 <a> 를 그대로 쓰고 모양만 버튼으로 입힌다
  linkButton: { display: "inline-flex", alignItems: "center", minHeight: "var(--control-min)", padding: "0 14px", borderRadius: "var(--radius-sm)", background: "var(--color-primary)", color: "var(--color-on-primary)", fontWeight: 500, whiteSpace: "nowrap" },

  // 링크를 흰 보조 버튼 모양으로 (예: 수정, 취소). 옆의 <button> 과 같은 높이·테두리
  linkButtonGhost: { display: "inline-flex", alignItems: "center", minHeight: "var(--control-min)", padding: "0 14px", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border-strong)", background: "var(--color-card)", color: "var(--color-foreground)", fontWeight: 500, whiteSpace: "nowrap" },

  // 상태 배지 (글자 + SVG 아이콘과 함께 쓴다. 부품은 lib/status-badge.tsx 의 StatusBadge)
  badgeDanger: { ...badgeBase, color: "var(--color-destructive)", background: "var(--color-destructive-bg)" }, // 부족·품절 위험
  badgeOk: { ...badgeBase, color: "var(--color-ok)", background: "var(--color-ok-bg)" }, // 정상
  badgeUnknown: { ...badgeBase, color: "var(--color-unknown)", background: "var(--color-unknown-bg)" }, // 판단 불가
  badgeInfo: { ...badgeBase, color: "var(--color-info)", background: "var(--color-info-bg)" }, // 발주 필요

  // 폼
  formGrid: fieldRow, // 입력 항목을 가로로 늘어놓는 폼 (항목 폭·버튼 위치는 globals.css 의 label·button 규칙)
  formGridWide: fieldRow, // 입출고 등록 폼 (예전엔 칸이 조금 넓었다. 지금은 항목이 남는 폭을 나눠 가져 따로 둘 필요가 없다)
  formStack: { display: "grid", gap: "12px", marginTop: "var(--space-lg)" }, // 세로로 쌓는 폼(로그인)
  fullRow: { gridColumn: "1 / -1", flexBasis: "100%" }, // 폼 줄에서 한 줄을 통째로 차지 (오류·완료 문장)
  buttons: { display: "flex", gap: "var(--space-sm)" }, // 버튼 가로 나열
  toolbar: { display: "flex", gap: "var(--field-row-gap) var(--field-gap)", flexWrap: "wrap", alignItems: "flex-start", margin: "var(--space-md) 0" }, // 필터 줄 (위쪽 기준 정렬)
  panel: { display: "flex", gap: "var(--field-row-gap) var(--field-gap)", flexWrap: "wrap", alignItems: "flex-start", padding: "12px", background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", margin: "var(--space-sm) 0" }, // 테두리 있는 작은 폼 상자
  basisFull: { flexBasis: "100%" }, // 상자 안에서 한 줄 차지
  block: { display: "block" }, // 이름 글자 아래에 선택 상자를 줄바꿈해 놓기
  blockFull: { display: "block", width: "100%" }, // 줄바꿈 + 가로 꽉 채움 입력칸
  searchBar: { display: "flex", gap: "var(--space-sm)", alignItems: "center", margin: "var(--space-md) 0" }, // 검색창 줄
  tableToolbar: { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "var(--space-sm) var(--space-md)", marginTop: "var(--space-md)", padding: "var(--space-sm) var(--space-md)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md) var(--radius-md) 0 0", background: "var(--color-card)" }, // 표 위에 검색과 필터를 묶고 좁으면 다음 줄로 보낸다
  inlineLabel: { marginLeft: "var(--space-md)" }, // 검색 줄 안의 체크박스 글자
  pager: { display: "flex", gap: "12px", alignItems: "center", marginTop: "12px" }, // 쪽 이동 줄
} satisfies Record<string, CSSProperties>;

// 비활성 행은 보조 글자색으로 낮춘다 (활성이면 그냥 본문 줄). 투명도(opacity)로 흐리면 글자 대비가 4.5:1 아래로 떨어져 색을 바꾼다
export function bodyRow(isActive: boolean): CSSProperties {
  return isActive ? S.row : { ...S.row, color: "var(--color-muted-foreground)" };
}
