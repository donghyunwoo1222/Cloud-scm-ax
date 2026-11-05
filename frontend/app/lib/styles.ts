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
const fieldRow: CSSProperties = { display: "flex", flexWrap: "wrap", gap: "var(--space-md)", alignItems: "flex-start", margin: "var(--space-md) 0" };

// 여러 화면이 같이 쓰는 스타일 이름 → 값
export const S = {
  // 레이아웃 (로그인 후 화면: 왼쪽 사이드 메뉴 + 오른쪽 상단 바·본문)
  shell: { display: "flex", flexWrap: "wrap", flex: 1 }, // 메뉴와 본문을 가로로. 좁은 화면에서는 메뉴가 위로 쌓인다
  sidebar: { flex: "1 1 220px", maxWidth: 240, background: "var(--color-card)", borderRight: "1px solid var(--color-border)", padding: "var(--space-md) 12px" }, // 사이드 메뉴 상자
  brand: { fontWeight: 700, fontSize: "var(--text-lg)", padding: "var(--space-xs) 12px var(--space-md)" }, // 메뉴 위 서비스 이름
  sideNav: { display: "flex", flexDirection: "column", gap: 2 }, // 메뉴 링크 세로 나열 (모양은 globals.css 의 .side-nav)
  content: { flex: "999 1 560px", minWidth: 0, display: "flex", flexDirection: "column" }, // 메뉴 오른쪽 전체 (표가 넓어도 화면 밖으로 밀지 않게 minWidth 0)
  topbar: { display: "flex", flexWrap: "wrap", justifyContent: "flex-end", alignItems: "center", gap: "var(--space-md)", padding: "12px var(--space-lg)", background: "var(--color-card)", borderBottom: "1px solid var(--color-border)", fontSize: "var(--text-sm)", color: "var(--color-muted-foreground)" }, // 상단 바: 내 정보·로그아웃
  main: { padding: "var(--space-lg)", maxWidth: 1360, width: "100%" }, // 본문 여백 (display 를 주지 않는다: hidden 속성이 먹어야 한다)
  pad2: { padding: "var(--space-xl)" }, // 안내 문구 여백
  loginPage: { padding: "48px", maxWidth: 360 }, // 로그인 화면 틀

  // 카드·제목·안내
  card: { background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", boxShadow: "var(--shadow-sm)", padding: "var(--space-md)" }, // 흰 카드 상자
  sectionTitle: { marginTop: "var(--space-xl)" }, // 화면 안의 두 번째 제목
  hint: { color: "var(--color-muted-foreground)" }, // 화면 설명·보조 글자
  empty: { padding: "var(--space-lg)", textAlign: "center", color: "var(--color-muted-foreground)" }, // 목록이 비었을 때 안내
  error: { color: "var(--color-destructive)" }, // 오류 문장
  ok: { color: "var(--color-ok)" }, // 성공 문장

  // 표
  table: { width: "100%", borderCollapse: "collapse" }, // 표: 가로 꽉 채우고 칸 사이 틈 없앰 (칸 모양은 globals.css 의 th·td)
  tableBox: { overflowX: "auto" }, // 표가 화면보다 넓으면 이 상자 안에서만 가로 스크롤
  headRow: { textAlign: "left" }, // 표 머리 줄: 글자 열은 왼쪽 정렬
  row: {}, // 표 본문 줄 (구분선은 globals.css 의 td 가 그린다)
  num: { textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }, // 숫자 칸: 오른쪽 정렬 + 숫자 폭 같게 (머리 칸에도 같이 쓴다)
  dim: { color: "var(--color-muted-foreground)" }, // 덜 중요한 숫자 (계산 재료)
  key: { fontWeight: 700 }, // 판단에 쓰는 핵심 숫자
  selectedRow: { background: "var(--color-selected)" }, // 체크한 줄
  selectedMark: { boxShadow: "inset 3px 0 0 var(--color-primary)" }, // 체크한 줄의 첫 칸 왼쪽 파란 세로줄

  // 상태 배지 (글자 + SVG 아이콘과 함께 쓴다)
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
  toolbar: { display: "flex", gap: "var(--space-md)", flexWrap: "wrap", alignItems: "flex-start", margin: "var(--space-md) 0" }, // 필터 줄 (위쪽 기준 정렬)
  panel: { display: "flex", gap: "var(--space-md)", flexWrap: "wrap", alignItems: "flex-start", padding: "12px", background: "var(--color-card)", border: "1px solid var(--color-border)", borderRadius: "var(--radius-md)", margin: "var(--space-sm) 0" }, // 테두리 있는 작은 폼 상자
  basisFull: { flexBasis: "100%" }, // 상자 안에서 한 줄 차지
  block: { display: "block" }, // 이름 글자 아래에 선택 상자를 줄바꿈해 놓기
  blockFull: { display: "block", width: "100%" }, // 줄바꿈 + 가로 꽉 채움 입력칸
  searchBar: { display: "flex", gap: "var(--space-sm)", alignItems: "center", margin: "var(--space-md) 0" }, // 검색창 줄
  inlineLabel: { marginLeft: "var(--space-md)" }, // 검색 줄 안의 체크박스 글자
  pager: { display: "flex", gap: "12px", alignItems: "center", marginTop: "12px" }, // 쪽 이동 줄
} satisfies Record<string, CSSProperties>;

// 비활성 행은 흐리게 (활성이면 그냥 본문 줄)
export function bodyRow(isActive: boolean): CSSProperties {
  return { ...S.row, opacity: isActive ? 1 : 0.5 };
}
