import { stampRows, type StampData } from "./stamp-layout"; // 줄 → y 좌표 계산 (순수 함수)

const RED = "#c62828"; // 도장 색 한 가지
const FONT = '"Noto Serif KR", "Nanum Myeongjo", serif'; // 굵은 명조 계열 시스템 글꼴만 (파일 추가 없음)

// 원형 도장 SVG. 글자는 React 텍스트 노드라 "A&B<주>" 도 이스케이프되어 그대로 보인다.
export function StampSeal({ stamp, companyName, size = 80 }: { stamp: StampData; companyName: string; size?: number }) {
  const layout = stampRows(stamp);
  if (!layout) return null; // 값이 이상하면 에러 없이 그리지 않는다
  return (
    <svg
      viewBox="0 0 100 100" width={size} height={size}
      role="img" aria-label={`회사 도장: ${companyName}`} // 스크린리더용 설명
      style={{ printColorAdjust: "exact", WebkitPrintColorAdjust: "exact" }} // 인쇄 때 도장 색이 빠지지 않게
    >
      <circle cx="50" cy="50" r="46" fill="none" stroke={RED} strokeWidth="4" /> {/* 바깥 굵은 원 */}
      <circle cx="50" cy="50" r="41" fill="none" stroke={RED} strokeWidth="1" /> {/* 안쪽 가는 원 */}
      {layout.rows.map((row, i) => (
        <text
          key={i} x="50" y={row.y} textAnchor="middle" dominantBaseline="central" // 가로·세로 중심 맞춤
          fontSize={layout.fontSize} fontFamily={FONT} fontWeight="900" fill={RED}
        >
          {row.text}
        </text>
      ))}
    </svg>
  );
}
