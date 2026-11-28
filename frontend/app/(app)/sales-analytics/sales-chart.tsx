import { barRatio, Bucket, isPartial, peakWord, trendLabel, TrendPoint } from "../../lib/sales-analytics"; // 구간 이름·막대 비율·부분 주
import { S } from "../../lib/styles"; // 화면 공통 스타일
import styles from "./page.module.css"; // 차트 스타일

// 판매 추이 막대 차트: 라이브러리 없이 인라인 SVG. 판매 없는 날·주도 0 으로 그린다(아주 얇은 회색 막대).
// 색만으로 읽지 않게 맨 위에 최대값 글자, 아래에 "숫자로 보기" 표를 같이 둔다. 7일이 안 되는 주는 빗금 막대 + "(N일)" 글자.
export function SalesChart({ trend, bucket, unitWord }: { trend: TrendPoint[]; bucket: Bucket; unitWord: string }) {
  const label = (p: TrendPoint) => trendLabel(p, bucket); // 예) "11/22 (1일)"
  const partial = trend.some((p) => isPartial(p, bucket));
  const max = Math.max(0, ...trend.map((p) => p.quantity)); // 가장 큰 구간
  const peak = trend.find((p) => p.quantity === max); // 그 구간 (최대가 0 이면 표시하지 않는다)
  const total = trend.reduce((sum, p) => sum + p.quantity, 0);
  const aria = `판매 추이 막대 차트. ${trend.length}개 구간, 합계 ${total.toLocaleString("ko-KR")}${unitWord}` + (peak && max > 0 ? `, 가장 많은 구간 ${label(peak)} ${max.toLocaleString("ko-KR")}${unitWord}` : "");
  const slot = 10; // 막대 한 칸의 폭 (viewBox 단위). 막대 7 + 틈 3
  return (
    <div>
      {peak && max > 0 && <p style={S.hint} className={styles.peak}>가장 많이 팔린 {peakWord(bucket)}: <strong>{label(peak)}</strong> · {max.toLocaleString("ko-KR")}{unitWord}</p>}
      <svg className={styles.chart} viewBox={`0 0 ${trend.length * slot} 100`} preserveAspectRatio="none" role="img" aria-label={aria}>
        <defs>
          <pattern id="partial-week" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="3" height="3" className={styles.partialBg} /><line x1="0" y1="0" x2="0" y2="3" className={styles.partialLine} />
          </pattern>
        </defs>
        <line x1="0" y1="99.5" x2={trend.length * slot} y2="99.5" className={styles.baseline} />
        {trend.map((p, i) => {
          const h = Math.max(barRatio(p.quantity, max) * 96, p.quantity > 0 ? 2 : 0); // 판매가 있으면 아주 작아도 보이게 최소 2
          return (
            <rect key={p.start} x={i * slot + 1.5} width="7" y={100 - h} height={h} className={isPartial(p, bucket) ? styles.barPartial : styles.bar}>
              <title>{`${label(p)}: ${p.quantity.toLocaleString("ko-KR")}${unitWord}`}</title>
            </rect>
          );
        })}
      </svg>
      <div className={styles.axis} aria-hidden="true">
        <span>{label(trend[0])}</span><span>{label(trend[trend.length - 1])}</span>
      </div>
      {partial && <p className={styles.partialNote}><span className={styles.partialSwatch} aria-hidden="true" />빗금 막대는 7일이 안 되는 주예요(기간 첫 주, 아직 진행 중인 이번 주).</p>}
      <details className={styles.numbers}>
        <summary>숫자로 보기</summary>
        <div className="table-box">
          <table style={{ ...S.table, minWidth: 0 }}>
            <thead><tr style={S.headRow}><th scope="col">{bucket === "week" ? "주" : "날짜"}</th><th scope="col" style={S.num}>판매 수량</th></tr></thead>
            <tbody>
              {trend.map((p) => (
                <tr key={p.start} style={S.row}><td>{label(p)}</td><td style={S.num}>{p.quantity.toLocaleString("ko-KR")}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
