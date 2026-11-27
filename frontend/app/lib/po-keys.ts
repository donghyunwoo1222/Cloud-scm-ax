// 발주 작성 폼의 키보드 규칙 (#358). 화면 없이 시험할 수 있게 판단만 따로 둔다.

export type EnterInput = {
  composing: boolean; // 한글 조합 중인지
  handled: boolean; // 후보 목록 같은 안쪽 입력칸이 이미 처리했는지 (defaultPrevented)
  kind: "field" | "other"; // 글자·숫자·날짜 입력칸이면 field, 버튼·선택·여러 줄 칸은 other
  combobox: boolean; // 품목 검색 칸인지
  inLastRow: boolean; // 마지막 품목 줄 안인지
  lastRowHasProduct: boolean; // 마지막 줄에 품목을 이미 골랐는지
};

// 예) 마지막 줄 수량 칸에서 Enter → "addLine", 공급업체 메모 칸에서 Enter → "block"(제출 막기), 조합 중 → "ignore"
export function enterAction(i: EnterInput): "ignore" | "block" | "addLine" {
  if (i.composing || i.handled || i.kind === "other") return "ignore"; // 조합 확정 Enter·후보 선택·버튼 Enter 는 건드리지 않는다
  if (i.combobox || !i.inLastRow || !i.lastRowHasProduct) return "block"; // 실수 제출만 막는다
  return "addLine";
}

// Ctrl+S (Mac 은 Cmd+S). Alt·Shift 가 섞이면 다른 단축키라 가로채지 않는다
export function isSaveShortcut(e: { key: string; ctrlKey: boolean; metaKey: boolean; altKey: boolean; shiftKey: boolean; repeat: boolean }) {
  return (e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && !e.repeat && e.key.toLowerCase() === "s";
}
