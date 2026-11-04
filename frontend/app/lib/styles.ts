// 화면 공통 스타일 모음. 인라인 style 을 화면마다 따로 쓰지 않고 여기서 가져다 쓴다.
// 6주차에 디자인을 입힐 때는 이 파일(과 globals.css)만 고치면 된다. 지금은 모양을 바꾸지 않고 모으기만 했다.
import type { CSSProperties } from "react"; // 인라인 스타일 객체의 타입

// 여러 화면이 같이 쓰는 스타일 이름 → 값
export const S = {
  table: { width: "100%", borderCollapse: "collapse" }, // 표: 가로 꽉 채우고 칸 사이 틈 없앰
  headRow: { textAlign: "left" }, // 표 머리 줄: 왼쪽 정렬
  row: { borderTop: "1px solid #ccc" }, // 표 본문 줄: 위에 얇은 구분선
  formGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.5rem", alignItems: "end", margin: "1rem 0" }, // 입력 칸들을 격자로 늘어놓는 폼
  formGridWide: { display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "0.5rem", alignItems: "end", margin: "1rem 0" }, // 칸이 조금 넓은 폼(입출고 등록)
  formStack: { display: "grid", gap: "0.75rem", marginTop: "1.5rem" }, // 세로로 쌓는 폼(로그인)
  fullRow: { gridColumn: "1 / -1" }, // 격자에서 한 줄을 통째로 차지
  buttons: { display: "flex", gap: "0.5rem" }, // 버튼 가로 나열
  toolbar: { display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "end", margin: "1rem 0" }, // 필터 줄
  panel: { display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "end", padding: "0.75rem", border: "1px solid #999", margin: "0.5rem 0" }, // 테두리 있는 작은 폼 상자
  basisFull: { flexBasis: "100%" }, // 상자 안에서 한 줄 차지
  block: { display: "block" }, // 이름 글자 아래에 선택 상자를 줄바꿈해 놓기
  blockFull: { display: "block", width: "100%" }, // 줄바꿈 + 가로 꽉 채움 입력칸
  sectionTitle: { marginTop: "2rem" }, // 화면 안의 두 번째 제목
  error: { color: "crimson" }, // 오류 문장
  ok: { color: "green" }, // 성공 문장
  searchBar: { display: "flex", gap: "0.5rem", alignItems: "center", margin: "1rem 0" }, // 검색창 줄
  inlineLabel: { marginLeft: "1rem" }, // 검색 줄 안의 체크박스 글자
  pager: { display: "flex", gap: "0.75rem", alignItems: "center", marginTop: "0.75rem" }, // 쪽 이동 줄
  header: { display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center", padding: "0.75rem 1.5rem", borderBottom: "1px solid #ccc" }, // 상단 바
  nav: { display: "flex", flexWrap: "wrap", gap: "1rem" }, // 상단 메뉴
  pushRight: { marginLeft: "auto" }, // 오른쪽 끝으로 밀기
  pad2: { padding: "2rem" }, // 안내 문구 여백
  main: { padding: "1.5rem" }, // 본문 여백
  loginPage: { padding: "3rem", maxWidth: 360 }, // 로그인 화면 틀
} satisfies Record<string, CSSProperties>;

// 비활성 행은 흐리게 (활성이면 그냥 본문 줄)
export function bodyRow(isActive: boolean): CSSProperties {
  return { ...S.row, opacity: isActive ? 1 : 0.5 };
}
