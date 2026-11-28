import { barRatio, bucketLabel, TrendPoint } from "../../lib/sales-analytics"; // 구간 이름·막대 비율
import { S } from "../../lib/styles"; // 화면 공통 스타일
import styles from "./page.module.css"; // 차트 스타일

// 판매 추이 막대 차트: 라이브러리 없이 인라인 SVG. 판매 없는 날·주도 0 으로 그린다(아주 얇은 회색 막대).
// 색만으로 읽지 않게 맨 위에 최대값 글자, 아래에 "숫자로 보기" 표를 같이 둔다.
export function SalesChart({ trend, unitWord }: { trend: TrendPoint[]; unitWord: string }) {
  const max = Math.max(0, ...trend.map((p) => p.quantity)); // 가장 큰 구간
  const peak = trend.find((p) => p.quantity === max); // 그 구간 (최대가 0 이면 표시하지 않는다)
  const total = trend.reduce((sum, p) => sum + p.quantity, 0);
  const label = `판매 추이 막대 차트. ${trend.length}개 구간, 합계 ${total.toLocaleString("ko-KR")}${unitWord}` + (peak && max > 0 ? `, 가장 많은 구간 ${bucketLabel(peak)} ${max.toLocaleString("ko-KR")}${unitWord}` : "");
  const slot = 10; // 막대 한 칸의 폭 (viewBox 단위). 막대 7 + 틈 3
  return (
    <div>
      {peak && max > 0 && <p style={S.hint} className={styles.peak}>가장 많이 팔린 {trend[0].start === trend[0].end ? "날" : "주"}: <strong>{bucketLabel(peak)}</strong> · {max.toLocaleString("ko-KR")}{unitWord}</p>}
      <svg className={styles.chart} viewBox={`0 0 ${trend.length * slot} 100`} preserveAspectRatio="none" role="img" aria-label={label}>
        <line x1="0" y1="99.5" x2={trend.length * slot} y2="99.5" className={styles.baseline} />
        {trend.map((p, i) => {
          const h = Math.max(barRatio(p.quantity, max) * 96, p.quantity > 0 ? 2 : 0); // 판매가 있으면 아주 작아도 보이게 최소 2
          return (
            <rect key={p.start} x={i * slot + 1.5} width="7" y={100 - h} height={h} className={styles.bar}>
              <title>{`${bucketLabel(p)}: ${p.quantity.toLocaleString("ko-KR")}${unitWord}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className={styles.axis} aria-hidden="true">
        <span>{bucketLabel(trend[0])}</span><span>{bucketLabel(trend[trend.length - 1])}</span>
      </div>
      <details className={styles.numbers}>
        <summary>숫자로 보기</summary>
        <div className="table-box">
          <table style={{ ...S.table, minWidth: 0 }}>
            <thead><tr style={S.headRow}><th scope="col">{trend[0].start === trend[0].end ? "날짜" : "주"}</th><th scope="col" style={S.num}>판매 수량</th></tr></thead>
            <tbody>
              {trend.map((p) => (
                <tr key={p.start} style={S.row}><td>{bucketLabel(p)}</td><td style={S.num}>{p.quantity.toLocaleString("ko-KR")}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
