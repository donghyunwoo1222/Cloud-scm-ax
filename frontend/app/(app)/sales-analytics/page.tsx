"use client"; // 기간·묶음 선택과 불러오기 상태를 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주 추천·판매 가져오기 이동 링크
import { usePathname, useRouter, useSearchParams } from "next/navigation"; // 주소의 ?days=&bucket= 읽고 바꾸기
import { Suspense, useCallback, useEffect, useRef, useState } from "react"; // 주소를 읽는 화면 감싸기, 함수 고정, 불러오기, 최신 요청 번호, 상태

import { api } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { skuWithOptions } from "../../lib/options"; // 품목 옵션 요약
import { BUCKET_OPTIONS, Bucket, coverText, DAY_OPTIONS, Days, isShortCover, parseQuery, SalesAnalytics, shareText, SHORT_COVER_DAYS, toQuery, TOP_N, visibleItems } from "../../lib/sales-analytics"; // 판매 분석 순수 함수
import { StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 배지
import { S } from "../../lib/styles"; // 화면 공통 스타일
import { SalesChart } from "./sales-chart"; // 판매 추이 막대 차트
import styles from "./page.module.css"; // 이 화면 스타일

// 판매 분석 화면 (주소 /sales-analytics): 기간 판매 추이 + 품목별 판매·ABC·소진 예상일. 읽기만 한다.
export default function Page() {
  return <Suspense fallback={<section><h1>판매 분석</h1><p>불러오는 중…</p></section>}><SalesAnalyticsRoute /></Suspense>;
}

function SalesAnalyticsRoute() {
  const params = useSearchParams();
  const { days, bucket } = parseQuery(params.get("days"), params.get("bucket")); // 모르는 값은 30일·일
  return <SalesAnalyticsView days={days} bucket={bucket} />;
}

function SalesAnalyticsView({ days, bucket }: { days: Days; bucket: Bucket }) {
  const router = useRouter();
  const pathname = usePathname();
  const [data, setData] = useState<SalesAnalytics | null>(null); // 응답 (불러오기 전·실패 시 null)
  const [error, setError] = useState<unknown>(null); // 불러오기 오류
  const [loading, setLoading] = useState(true); // 불러오는 중
  const [expanded, setExpanded] = useState(false); // 품목 표를 TOP N 이상 펼쳤는지
  const latest = useRef(0); // 조건을 연달아 바꿨을 때 최신 요청만 반영한다

  const load = useCallback(async () => {
    const request = ++latest.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api<SalesAnalytics>(`/sales-analytics?${toQuery(days, bucket)}`); // 회사는 서버가 토큰에서 정한다
      if (request === latest.current) setData(result);
    } catch (e) {
      if (request === latest.current) { setData(null); setError(e); }
    } finally {
      if (request === latest.current) setLoading(false);
    }
  }, [days, bucket]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 화면이 열리거나 기간·묶음이 바뀔 때 응답을 불러와 상태에 넣는 것이 이 효과의 목적이다
    load();
  }, [load]);

  function choose(nextDays: Days, nextBucket: Bucket) {
    setExpanded(false); // 조건이 바뀌면 다시 TOP N 부터
    router.replace(`${pathname}?${toQuery(nextDays, nextBucket)}`, { scroll: false }); // 새로고침해도 남도록 주소에 기록
  }

  const units = new Set((data?.items ?? []).filter((i) => i.quantity > 0).map((i) => i.unit));
  const unitWord = units.size === 1 ? [...units][0] : ""; // 단위가 하나뿐일 때만 합계에 붙인다
  const items = data ? visibleItems(data.items, expanded) : [];
  const hidden = data ? data.items.length - items.length : 0;
  const empty = !!data && data.total_quantity === 0; // 이 기간에 판매가 없다

  return (
    <section>
      <h1>판매 분석</h1>
      <p style={S.hint}>판매 출고 이력을 모아 어떤 품목이 얼마나 팔리는지, 재고가 며칠 버틸지 봅니다.</p>

      <div className={styles.controls}>
        <div className={styles.controlGroup} role="group" aria-label="기간">
          <span className={styles.controlLabel}>기간</span>
          <span style={S.detailFilterGroup}>
            {DAY_OPTIONS.map((d) => (
              <button key={d} type="button" aria-pressed={d === days} style={{ ...S.detailFilterButton, ...(d === days ? S.detailFilterSelected : {}) }} onClick={() => choose(d, bucket)}>최근 {d}일</button>
            ))}
          </span>
        </div>
        <div className={styles.controlGroup} role="group" aria-label="묶음">
          <span className={styles.controlLabel}>묶음</span>
          <span style={S.detailFilterGroup}>
            {BUCKET_OPTIONS.map(([value, name]) => (
              <button key={value} type="button" aria-pressed={value === bucket} style={{ ...S.detailFilterButton, ...(value === bucket ? S.detailFilterSelected : {}) }} onClick={() => choose(days, value)}>{name}별</button>
            ))}
          </span>
        </div>
      </div>

      {loading && !data && !error && <p role="status">불러오는 중…</p>}
      {error != null && (
        <div role="alert">
          <ErrorText error={error} />
          <button type="button" onClick={load}>다시 시도</button>
        </div>
      )}

      {data && empty && (
        <div style={S.card}>
          <p style={S.empty}>이 기간에는 판매 기록이 없어요. 판매 파일을 가져오면 여기에 분석이 나와요.</p>
          <p style={{ textAlign: "center" }}><Link href="/sales-import" style={S.linkButton}>판매 가져오기로 이동</Link></p>
        </div>
      )}

      {data && !empty && (
        <>
          <div style={S.kpiGrid}>
            <div style={S.kpiCard}>
              <span style={S.kpiLabel}>기간 총 판매 수량</span>
              <span style={S.kpiValue}>{data.total_quantity.toLocaleString("ko-KR")}{unitWord}</span>
              <span style={S.kpiSub}>{data.period.start} ~ {data.period.end} ({data.period.days}일)</span>
            </div>
          </div>

          <div style={S.sectionCard} aria-busy={loading}>
            <h2 style={{ marginTop: 0 }}>판매 추이</h2>
            <SalesChart trend={data.trend} unitWord={unitWord} />
          </div>

          <h2 style={S.sectionTitle}>품목별 판매</h2>
          <div className={styles.legend}>
            <p>등급: A = 판매의 약 80%를 차지하는 핵심 품목, B = 그다음 약 15%, C = 나머지 약 5%.</p>
            <p>일평균·현재고·소진 예상일은 최근 30일 판매 기준이에요. 위에서 고른 기간과 상관없어요.</p>
          </div>
          <div className="table-box">
            <table style={S.table} className={styles.cards}>
              <thead>
                <tr style={S.headRow}>
                  <th scope="col" style={S.midCol}>품목</th>
                  <th scope="col" style={S.num}>판매 수량</th>
                  <th scope="col" style={S.num}>비중</th>
                  <th scope="col">등급</th>
                  <th scope="col" style={S.num}>일평균(30일)</th>
                  <th scope="col" style={S.num}>현재고</th>
                  <th scope="col">소진 예상일</th>
                </tr>
              </thead>
              <tbody>
                {items.map((i) => {
                  const short = isShortCover(i); // 곧 소진: 배지(글자+아이콘)와 링크로 알린다
                  return (
                    <tr key={i.product_id} style={S.row}>
                      <td className={styles.nameCell} data-label="품목">
                        <span className={styles.itemName}>{i.product_name}</span>
                        <span style={S.sub}>{skuWithOptions(i.product_sku, i)}</span>
                      </td>
                      <td style={S.num} data-label="판매 수량">{i.quantity.toLocaleString("ko-KR")}{i.unit}</td>
                      <td style={S.num} data-label="비중">{shareText(i.share)}</td>
                      <td data-label="등급">{i.abc_grade}</td>
                      <td style={S.num} data-label="일평균(30일)">{i.avg_daily_sales === null ? null : `${i.avg_daily_sales.toFixed(1)}${i.unit}`}</td>
                      <td style={S.num} data-label="현재고">{i.current_stock.toLocaleString("ko-KR")}{i.unit}</td>
                      <td className={styles.coverCell} data-label="소진 예상일">
                        {short && <><StatusBadge kind="danger">곧 소진</StatusBadge>{" "}</>}
                        <span style={short ? S.key : undefined}>{coverText(i)}</span>
                        {short && <Link className={styles.coverLink} href={`/recommendations?product_id=${i.product_id}`}>발주 추천에서 보기</Link>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p style={S.hint}>{SHORT_COVER_DAYS}일 이하로 남은 품목에 “곧 소진”을 붙여요.</p>
          {data.items.length > TOP_N && (
            <p className={styles.more}>
              <button type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
                {expanded ? `상위 ${TOP_N}개만 보기` : `더 보기 (${hidden}개)`}
              </button>
            </p>
          )}
          {data.source === "SALE_MOVEMENTS" && <p className={styles.source}>이 분석은 판매 출고 이력의 수량 기준이에요. 금액은 아직 계산하지 않아요.</p>}
        </>
      )}
    </section>
  );
}
