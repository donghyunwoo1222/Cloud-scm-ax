"use client"; // 서버에서 불러온 요약을 상태로 그리는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주·재고 화면 링크
import { ReactNode, useEffect, useState } from "react"; // 카드 안 내용 타입, 처음 한 번 실행, 상태

import { api, apiList } from "../../lib/api"; // 공통 API 호출 함수 (한 건, 목록)
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { useMe } from "../../lib/me"; // 내 역할 (세 번째 카드가 역할마다 다르다)
import { seoulToday } from "../../lib/movement-form"; // 이력 링크에 서울 기준 오늘을 쓴다
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일
import styles from "./page.module.css"; // 입고 카드의 전체·세부 목록 링크

// GET /api/v1/dashboard 응답 (backend/app/services/dashboard.py)
type UnitTotals = Record<string, number>; // 단위별 합계
const unitTotals = (totals: UnitTotals) => Object.entries(totals).map(([unit, qty]) => qty.toLocaleString("ko-KR") + unit).join(" · ") || "없음";

type Dashboard = {
  purchase_orders: {
    draft: number; approved: number; ordered: number; incoming_by_unit: UnitTotals;
    due_today?: number; overdue?: number; // 이전 API 응답에는 납기별 건수가 없을 수 있다
  };
  month: { month_start: string; month_end: string; in_count: number; out_count: number }; // 이번 달 입고·출고 기록 건수
  dead_stock: { days: number; count: number; items: DeadItem[] }; // 장기재고 (기준 일수, 전체 건수, 화면에 보일 줄)
  shortage: { count: number; items: ShortItem[] }; // 부족 품목 (전체 건수, 화면에 보일 20줄)
  overstock: { days: number; count: number; items: OverItem[] }; // 과잉재고 (기준 일수 90, 전체 건수, 20줄)
};
type ShortItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; available: number; reorder_point: number; recommended_quantity: number };
type OverItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; avg_daily_sales: number };

// 소수는 첫째 자리까지, 정수는 그대로 (추천 화면과 같은 방식, 예: 3.1666 → "3.2", 70 → "70")
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
type DeadItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; last_sale_date: string | null };

// 재주문점이 0이면 퍼센트를 만들 수 없어 수량만 보여 준다.
const stockRatio = (item: ShortItem) => item.reorder_point > 0 ? item.available / item.reorder_point : null;
const SHORTAGE_PREVIEW_LIMIT = 5; // 첫 화면에 보여 줄 부족 품목 수

// 숫자 카드 하나: 이름 · 큰 숫자 · 보조 글자. href 가 있으면 카드 전체가 링크(사용자 결정)이고 맨 아래에 "… 보기 →" 를 항상 보여 누를 수 있음을 알린다
function NumberCard({ label, value, sub, href, more }: { label: string; value: string; sub?: ReactNode; href?: string; more?: string }) {
  const body = (
    <>
      <span style={S.kpiLabel}>{label}</span>
      {/* 카드 이름 (예: 발주 추천) */}
      <span style={S.kpiValue}>{value}</span>
      {/* 큰 숫자 (예: 5건) */}
      {sub && <span style={S.kpiSub}>{sub}</span>}
      {/* 보조 설명 (예: 입고 예정 155개) */}
      {more && <span style={S.kpiMore}>{more} →</span>}{/* 카드마다 어디로 가는지 다른 문구로 알린다 */}
    </>
  );
  return href
    ? <Link href={href} className="kpi-card" style={S.kpiCard}>{body}</Link> // 누르면 걸러진 목록으로 (테두리 강조는 globals.css 의 .kpi-card)
    : <div style={S.kpiCard}>{body}</div>; // 이동할 곳이 없는 숫자(이번 달 입출고)는 그냥 상자
}

// 오늘 할 일에서 시작해 재고 점검과 입출고 이력으로 이어진다.
export default function Page() {
  const me = useMe(); // 내 정보 (레이아웃이 로그인을 확인하기 전에는 null)
  const [data, setData] = useState<Dashboard | null>(null); // 불러온 요약 (불러오기 전 null)
  const [error, setError] = useState<unknown>(null); // 불러오기 오류
  const [hasSupplier, setHasSupplier] = useState<boolean | null>(null); // 첫 설정에서 가능한 다음 단계를 찾는다.
  const [productTotal, setProductTotal] = useState<number | null>(null); // 등록한 품목 수 (부족이 0일 때만 묻는다, 모르면 null)
  const [unknownTotal, setUnknownTotal] = useState<number | null>(null); // 판단 불가 품목 수 (품목이 있고 부족이 0일 때만 묻는다)
  const [showMoreStock, setShowMoreStock] = useState(false);

  useEffect(() => {
    // 처음 열 때 한 번: 요약을 불러오고, 부족이 0일 때만 빈 화면 문구에 필요한 숫자를 더 묻는다
    api<Dashboard>("/dashboard").then(async (d) => {
      setData(d); // 요약 먼저 그린다
      if (d.shortage.count > 0) return; // 부족 품목이 있으면 품목이 있는 게 확실하니 더 묻지 않는다
      try {
        const products = await apiList("/products?page_size=1&include_inactive=true"); // 한 줄만 받아 전체 개수(meta.total)만 본다. 비활성만 있어도 "등록한 품목 있음"
        setProductTotal(products.meta.total); // 0 이면 "첫 품목 등록" 안내
        if (products.meta.total === 0) {
          const suppliers = await apiList("/suppliers?page_size=1"); // 새 품목에는 활성 공급업체가 필요하다.
          setHasSupplier(suppliers.meta.total > 0);
          return;
        }
        const unknown = await apiList("/stock?status=UNKNOWN&page_size=1"); // 판단 불가(데이터 부족 등) 품목 개수
        setUnknownTotal(unknown.meta.total); // "판단 불가 N개" 로 함께 보인다
      } catch {
        // 보조 숫자를 못 불러와도 대시보드는 그대로 보인다 (문구만 기본 문장으로)
      }
    }).catch(setError); // 요약 자체를 못 불러오면 오류 문장
  }, []);

  if (error) return <section><h1>대시보드</h1><ErrorText error={error} /></section>; // 오류면 문장만
  if (!data) return <section><h1>대시보드</h1><p>불러오는 중…</p></section>; // 불러오기 전

  const { purchase_orders: po, month, dead_stock: dead, shortage, overstock: over } = data; // 이름 줄이기
  // 서버가 보낸 품목 안에서 현재고 0을 먼저, 그다음 재주문점에 가장 못 미치는 순으로 보여 준다.
  const shortageItems = [...shortage.items].sort((a, b) =>
    Number(b.current_stock === 0) - Number(a.current_stock === 0) || (stockRatio(a) ?? 1) - (stockRatio(b) ?? 1)
  ).slice(0, SHORTAGE_PREVIEW_LIMIT);
  const won = (n: number) => n.toLocaleString(); // 천 단위 쉼표 (예: 1497 → "1,497")
  const today = seoulToday();
  const stockLimit = showMoreStock ? 20 : 3;
  const overItems = over.items.slice(0, stockLimit);
  const deadItems = dead.items.slice(0, stockLimit);
  const overScale = Math.max(over.days * 2, ...overItems.map((item) => item.current_stock / item.avg_daily_sales));

  return (
    <section>
      <h1>대시보드</h1>
      {productTotal === 0 && (
        <section style={S.sectionCard}>
          <h2>첫 재고 설정</h2>
          <p>공급업체 등록 → 품목 등록 → 첫 입고</p>
          <div style={{ ...S.buttons, marginTop: "var(--space-sm)" }}>
            {hasSupplier !== true && <Link href="/suppliers" style={S.linkButton}>공급업체 등록</Link>}
            {hasSupplier !== false && <Link href="/products" style={hasSupplier ? S.linkButton : S.linkButtonGhost}>품목 등록</Link>}
          </div>
        </section>
      )}
      {/* 품목이 하나도 없는 회사: 무엇부터 할지 안내 (빈 화면 대신 다음 행동) */}

      <h2 style={S.sectionTitle}>오늘 확인할 일</h2>
      <div role="group" aria-label="오늘 확인할 일" style={S.kpiGrid}>
        <div className={`kpi-card ${styles.receiptCard}`} style={S.kpiCard}>
          <span style={S.kpiLabel}>입고 대기 발주</span>
          {po.due_today != null && po.overdue != null && (
            <div className={styles.receiptLinks}>
              <Link href="/purchase-orders?status=ORDERED&receipt_due=TODAY"><span>오늘</span>{" "}<strong>{won(po.due_today)}건</strong></Link>
              <Link href="/purchase-orders?status=ORDERED&receipt_due=OVERDUE"
                className={po.overdue > 0 ? styles.lateReceipts : undefined}><span>지연</span>{" "}<strong>{won(po.overdue)}건</strong></Link>
            </div>
          )}
          <span style={S.kpiSub}>전체 {won(po.ordered)}건 · 입고 예정 {unitTotals(po.incoming_by_unit)}</span>
          <Link className={styles.allReceipts} href="/purchase-orders?status=ORDERED" style={S.kpiMore}>입고 대기 발주 보기 →</Link>
        </div>
        <NumberCard label="발주 검토" value={`${won(shortage.count)}품목`} href="/recommendations" more="발주 추천 보기" />
        {me?.role === "ADMIN" && (
          <NumberCard label="승인할 발주" value={`${won(po.draft)}건`} sub="승인 전 초안" href="/purchase-orders?status=DRAFT" more="승인할 발주 보기" />
        )}
        {/* 3-관리자: 내가 승인해야 할 발주서 */}
        {me?.role === "STAFF" && (
          <NumberCard label="보낼 발주" value={`${won(po.approved)}건`} sub="공급업체에 보낼 승인 발주서" href="/purchase-orders?status=APPROVED" more="보낼 발주 보기" />
        )}
        {/* 3-담당자: 승인이 나서 공급업체에 보낼 발주서 */}
      </div>

      {/* 항목마다 흰 카드 한 장. 카드 안 제목(h2)은 위 여백을 없앤다 */}
      <div style={S.sectionCard}>
        <h2>발주 검토가 필요한 품목 ({won(shortage.count)}개)</h2>
        {shortage.count === 0 ? (
          productTotal === 0 ? <p style={S.empty}>등록한 품목이 없습니다.</p> : (
            <p style={S.empty}>
              현재 기준에 해당하는 부족 품목이 없습니다.
              {unknownTotal !== null && unknownTotal > 0 && (
                <> (<Link href="/inventory?status=UNKNOWN">판단 불가 {won(unknownTotal)}개</Link>)</>
              )}
              {/* 판단 불가(판매 기록 부족 등) 품목은 "부족 없음"에 숨지 않게 개수를 함께 보이고 재고 현황으로 잇는다 */}
            </p>
          )
        ) : (
          <>
            <p style={S.hint}>현재고 0인 품목을 먼저 표시합니다. 가용재고는 현재고와 입고 예정 수량의 합입니다.</p>
            <div style={S.tableBox}>
              <table style={{ ...S.table, minWidth: 520 }}>
                <thead>
                  <tr style={S.headRow}>
                    <th scope="col">품목</th><th scope="col" style={S.num}>현재고</th><th scope="col" style={S.num}>가용재고 / 재주문점</th><th scope="col" style={S.num}>추천 수량</th>
                  </tr>
                </thead>
                <tbody>
                  {shortageItems.map((i) => {
                    const ratio = stockRatio(i);
                    return (
                      <tr key={i.product_id} style={bodyRow(true)}>
                        <th scope="row" style={{ textAlign: "left", fontWeight: 500, background: "transparent", color: "var(--color-foreground)" }}>
                          {i.name}<span style={S.sub}>{i.sku}</span>
                          {/* 품목 바로 아래에 두어 좁은 화면에서도 작업 링크가 먼저 보인다. */}
                          <Link href={`/recommendations?product_id=${i.product_id}`} style={S.nowrap}
                            aria-label={`${i.name} (${i.sku}) 발주 검토`}>발주 검토 →</Link>
                        </th>
                        <td style={S.num}>
                          {i.current_stock === 0 ? <strong style={{ color: "var(--color-destructive)" }}>0{i.unit}</strong> : <>{won(i.current_stock)}{i.unit}</>}
                        </td>
                        <td style={{ ...S.num, minWidth: "10rem" }}>
                          <span style={S.nowrap}>{won(i.available)} / {fmt(i.reorder_point)}{i.unit}</span>
                          {ratio === null ? <span style={S.sub}>재주문점 0</span> : (
                            <>
                              <span aria-hidden="true" style={{
                                display: "block", marginBlock: "var(--space-xs)", height: "var(--space-sm)",
                                background: "var(--color-muted)", borderRadius: "var(--radius-sm)", overflow: "hidden",
                              }}>
                                <span style={{ display: "block", width: `${ratio * 100}%`, height: "100%", background: "var(--color-primary)" }} />
                              </span>
                              <span style={S.sub}>재주문점의 {fmt(ratio * 100)}%</span>
                            </>
                          )}
                        </td>
                        <td style={S.num}>{won(i.recommended_quantity)}{i.unit}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {shortage.count > shortageItems.length && <p style={S.hint}>
              {shortage.count > shortage.items.length
                ? `최근 등록한 부족 품목 ${won(shortage.items.length)}개 중 ${shortageItems.length}개를 표시합니다.`
                : `부족 품목 ${won(shortage.count)}개 중 ${shortageItems.length}개를 표시합니다.`}
            </p>}
            <p><Link href="/inventory?status=SHORTAGE">부족 품목 전체 보기 →</Link></p>
          </>
        )}
      </div>

      <p className={styles.orderLink}><Link href="/purchase-orders">발주 목록 전체 보기 →</Link></p>

      <section style={S.sectionCard}>
        <h2>재고 점검</h2>
        {over.count === 0 && dead.count === 0 ? <p style={S.hint}>현재 기준으로 점검할 재고가 없습니다.</p> : (
          <>
            <div className={styles.reviewGrid} id="stock-review-list">
              {over.count > 0 && <section>
                <h3>과잉재고 <span>{won(over.count)}품목</span></h3>
                <p style={S.hint}>최근 30일 판매 속도 기준 {over.days}일치 이상</p>
                <ul className={styles.reviewList}>
                  {overItems.map((item) => {
                    const days = item.current_stock / item.avg_daily_sales;
                    return <li key={item.product_id}>
                      <Link href={`/inventory?product_id=${item.product_id}#movement-history`}>{item.name} <span style={S.sub}>{item.sku}</span></Link>
                      <p>현재고 {won(item.current_stock)}{item.unit} · <strong>약 {won(Math.round(days))}일치</strong></p>
                      <div className={styles.coverageBar} aria-hidden="true">
                        <span style={{ width: `${days / overScale * 100}%` }} />
                        <i style={{ left: `${over.days / overScale * 100}%` }} />
                      </div>
                    </li>;
                  })}
                </ul>
                <p style={S.hint}>막대의 세로선은 {over.days}일 기준입니다.{over.count > overItems.length && ` · ${overItems.length}품목 표시`}</p>
              </section>}
              {dead.count > 0 && <section>
                <h3>장기재고 <span>{won(dead.count)}품목</span></h3>
                <p style={S.hint}>판매가 {dead.days}일 넘게 없는 재고 · 신규 품목 제외</p>
                <ul className={styles.reviewList}>
                  {deadItems.map((item) => <li key={item.product_id}>
                    <Link href={`/inventory?product_id=${item.product_id}#movement-history`}>{item.name} <span style={S.sub}>{item.sku}</span></Link>
                    <p>현재고 {won(item.current_stock)}{item.unit} · <strong>{item.last_sale_date
                      ? `마지막 판매 ${won(Math.round((Date.parse(today) - Date.parse(item.last_sale_date)) / 86_400_000))}일 전`
                      : "판매 기록 없음"}</strong></p>
                  </li>)}
                </ul>
                {dead.count > deadItems.length && <p style={S.hint}>재고가 많은 {deadItems.length}품목 표시</p>}
              </section>}
            </div>
            {(over.items.length > 3 || dead.items.length > 3) && (
              <button className={styles.reviewToggle} type="button" aria-expanded={showMoreStock} aria-controls="stock-review-list"
                onClick={() => setShowMoreStock(!showMoreStock)}>{showMoreStock ? "접기" : "점검 품목 더 보기"}</button>
            )}
          </>
        )}
      </section>

      <Link className={`kpi-card ${styles.monthRow}`} style={S.sectionCard}
        href={`/inventory?summary=month&date_from=${month.month_start}&date_to=${month.month_end}#movement-history`}>
        <strong>이번 달 입출고</strong>
        <span>입고 <strong>{won(month.in_count)}건</strong> · 출고 <strong>{won(month.out_count)}건</strong></span>
        <span className={styles.monthLink}>입출고 이력 보기 →</span>
      </Link>
    </section>
  );
}
