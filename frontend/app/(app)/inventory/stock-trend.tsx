"use client";

import { useEffect, useId, useState } from "react";

import { api } from "../../lib/api";
import { ErrorText } from "../../lib/list";
import { quantityLabel } from "../../lib/po";
import { S } from "../../lib/styles";

type TrendDay = { day: string; closing_stock: number | null; received_quantity: number; reached_zero: boolean };
type Trend = { name: string; sku: string; unit: string; days: TrendDay[] };

function dateLabel(day: string) {
  return `${Number(day.slice(5, 7))}월 ${Number(day.slice(8, 10))}일`;
}

export function StockTrend({ productId }: { productId: string }) {
  const headingId = useId();
  const dateInputId = `${headingId}-day`;
  const [trend, setTrend] = useState<Trend | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0); // 요청에 실패하면 같은 품목을 다시 읽을 수 있다
  const [dayIndex, setDayIndex] = useState<number | null>(null); // 기본은 오늘

  useEffect(() => {
    let active = true; // 품목을 바꾼 뒤 늦게 도착한 응답을 버린다
    api<Trend>(`/stock/${productId}/trend`).then((result) => {
      if (active) setTrend(result);
    }).catch((reason) => {
      if (active) setError(reason);
    });
    return () => { active = false; };
  }, [productId, attempt]);

  const days = trend?.days ?? [];
  const last = days.length - 1;
  const index = dayIndex ?? last;
  const selected = days[index];
  const known = days.flatMap((day) => day.closing_stock === null ? [] : [day.closing_stock]);
  const low = Math.min(0, ...known); // 과거 이력을 날짜별로 재구성했을 때의 음수도 그대로 그린다
  const high = Math.max(1, ...known);
  const x = (offset: number) => 4 + offset / Math.max(1, last) * 292;
  const y = (stock: number) => 148 - (stock - low) / (high - low) * 144;
  const latestReceipt = days.map((day) => day.received_quantity > 0).lastIndexOf(true);
  const latestZero = days.map((day) => day.reached_zero).lastIndexOf(true);
  const points = days.flatMap((day, offset) => day.closing_stock === null ? [] : [`${x(offset)},${y(day.closing_stock)}`]);

  return (
    <section aria-labelledby={headingId} style={S.sectionCard}>
      <h3 id={headingId} style={{ margin: 0 }}>최근 30일 재고 추이</h3>
      {error ? (
        <><ErrorText error={error} /><button type="button" onClick={() => { setError(null); setAttempt(attempt + 1); }}>다시 시도</button></>
      ) : !trend ? <p role="status" style={S.hint}>재고 추이 불러오는 중…</p> : (
        <>
          <p style={S.hint}>{trend.name} · {trend.sku} · 하루 마감 기준, 오늘은 현재까지</p>
          {known.length === 0 || !selected ? <p style={S.empty}>이 품목의 입출고 기록이 아직 없습니다.</p> : (
            <>
              <div role="status" style={{ ...S.num, textAlign: "left", marginBlock: "var(--space-sm)" }}>
                <span>{dateLabel(selected.day)}{index === last ? " · 현재까지" : " 마감"}</span>
                {" · "}<strong>{selected.closing_stock === null ? "기록 없음" : quantityLabel(selected.closing_stock, trend.unit)}</strong>
                {selected.received_quantity > 0 && <> · 입고 {quantityLabel(selected.received_quantity, trend.unit)}</>}
                {selected.reached_zero && <> · 재고 0 도달</>}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "auto minmax(0, 1fr)", gap: "var(--space-xs) var(--space-sm)" }}>
                <div aria-hidden="true" style={{ ...S.num, display: "flex", flexDirection: "column", justifyContent: "space-between", color: "var(--color-muted-foreground)" }}>
                  <span>{high.toLocaleString("ko-KR")}</span><span>{low.toLocaleString("ko-KR")}</span>
                </div>
                <svg viewBox="0 0 300 152" preserveAspectRatio="none" width="100%" height="152"
                  role="img" aria-label={`${trend.name}의 최근 30일 일별 재고 그래프, 단위 ${trend.unit}`}>
                  <path d="M4 4H296 M4 148H296" fill="none" stroke="var(--color-border-strong)" vectorEffect="non-scaling-stroke" />
                  {low < 0 && <line x1={4} x2={296} y1={y(0)} y2={y(0)} stroke="var(--color-border-strong)" vectorEffect="non-scaling-stroke" />}
                  <line x1={x(index)} x2={x(index)} y1={4} y2={148} stroke="var(--color-muted-foreground)" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
                  <polyline points={points.join(" ")} fill="none" stroke="var(--color-primary)" strokeWidth={2.5}
                    strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                  {selected.closing_stock !== null && (
                    <circle cx={x(index)} cy={y(selected.closing_stock)} r={2.5} fill="var(--color-primary)" />
                  )}
                </svg>
                <div aria-hidden="true" style={{ gridColumn: 2, display: "flex", justifyContent: "space-between", ...S.hint }}>
                  <span>{dateLabel(days[0].day)}</span><span>{dateLabel(days[last].day)}</span>
                </div>
              </div>
              <label htmlFor={dateInputId} style={{ ...S.hint, display: "block", marginTop: "var(--space-sm)" }}>날짜 선택</label>
              <input id={dateInputId} type="range" min={0} max={last} value={index}
                aria-valuetext={`${dateLabel(selected.day)} ${selected.closing_stock === null ? "기록 없음" : quantityLabel(selected.closing_stock, trend.unit)}`}
                onChange={(event) => setDayIndex(Number(event.target.value))} style={{ display: "block", width: "100%", accentColor: "var(--color-primary)" }} />
              <div style={{ ...S.buttons, marginTop: "var(--space-sm)" }}>
                {latestReceipt >= 0 && <button type="button" aria-pressed={index === latestReceipt}
                  onClick={() => setDayIndex(latestReceipt)}>최근 입고 · {dateLabel(days[latestReceipt].day)}</button>}
                {latestZero >= 0 && <button type="button" aria-pressed={index === latestZero}
                  onClick={() => setDayIndex(latestZero)}>최근 재고 0 · {dateLabel(days[latestZero].day)}</button>}
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
