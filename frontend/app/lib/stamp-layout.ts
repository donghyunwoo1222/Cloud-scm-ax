// 도장 글자 배치 계산 (순수 함수). 줄 나누기·글자 크기 비율은 서버(stamp_of)가 정하고, 여기서는 받은 값을 좌표로만 바꾼다.
export type StampData = { lines: string[]; ratio: number };
export type StampRow = { text: string; y: number }; // y = 그 줄 글자의 세로 중심 (viewBox 0~100 기준)

// 이상한 값이면 null (도장을 그리지 않는다). 예) lines 비었음, ratio 0·NaN
export function stampRows(stamp: StampData | null | undefined): { fontSize: number; rows: StampRow[] } | null {
  if (!stamp || !Array.isArray(stamp.lines) || stamp.lines.length === 0) return null;
  if (!stamp.lines.every((t) => typeof t === "string" && t.length > 0)) return null;
  if (!Number.isFinite(stamp.ratio) || stamp.ratio <= 0) return null;
  const fontSize = stamp.ratio * 100; // 지름 1 = 100 단위. 예) ratio 0.233 → 23.3
  const gap = fontSize * 1.1; // 줄 간격 = 글자 크기 × 1.1
  const n = stamp.lines.length;
  // 예) 2줄, 글자 35 → gap 38.5, y = 50 + (0 − 0.5)×38.5 = 30.75, 69.25 (묶음 전체가 원 세로 중앙)
  return { fontSize, rows: stamp.lines.map((text, i) => ({ text, y: 50 + (i - (n - 1) / 2) * gap })) };
}
