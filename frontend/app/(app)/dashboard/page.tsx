"use client"; // 서버에서 불러온 요약을 상태로 그리는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주·재고 화면 링크
import { ReactNode, useEffect, useState } from "react"; // 카드 안 내용 타입, 처음 한 번 실행, 상태

import { api, apiList } from "../../lib/api"; // 공통 API 호출 함수 (한 건, 목록)
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
import { useMe } from "../../lib/me"; // 내 역할 (세 번째 카드가 역할마다 다르다)
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/dashboard 응답 (backend/app/services/dashboard.py)
type Dashboard = {
  purchase_orders: { draft: number; approved: number; ordered: number; incoming_quantity: number }; // 진행 중 발주 건수와 입고 예정 수량
  month: { month_start: string; in_quantity: number; out_quantity: number }; // 이번 달 입고·출고 수량
  dead_stock: { days: number; count: number; items: DeadItem[] }; // 장기재고 (기준 일수, 전체 건수, 화면에 보일 줄)
  shortage: { count: number; items: ShortItem[] }; // 부족 품목 (전체 건수, 화면에 보일 20줄)
  overstock: { days: number; count: number; items: OverItem[] }; // 과잉재고 (기준 일수 90, 전체 건수, 20줄)
};
type ShortItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; available: number; reorder_point: number; recommended_quantity: number };
type OverItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; avg_daily_sales: number };

// 소수는 첫째 자리까지, 정수는 그대로 (추천 화면과 같은 방식, 예: 3.1666 → "3.2", 70 → "70")
const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(1));
type DeadItem = { product_id: number; sku: string; name: string; unit: string; current_stock: number; last_sale_date: string | null };

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
      {href && <span style={S.kpiMore}>{more ?? "목록 보기"} →</span>}
      {/* 마우스를 올리지 않아도 눌리는 카드임을 글자로 보인다 */}
    </>
  );
  return href
    ? <Link href={href} className="kpi-card" style={S.kpiCard}>{body}</Link> // 누르면 걸러진 목록으로 (테두리 강조는 globals.css 의 .kpi-card)
    : <div style={S.kpiCard}>{body}</div>; // 이동할 곳이 없는 숫자(이번 달 입출고)는 그냥 상자
}

// 대시보드 화면 (주소 /dashboard): 로그인 후 시작 화면. 위 → 아래로 "할 일 숫자 → 진행 중 발주 → 부족 → 이번 달 → 과잉·장기"
export default function Page() {
  const me = useMe(); // 내 정보 (레이아웃이 로그인을 확인하기 전에는 null)
  const [data, setData] = useState<Dashboard | null>(null); // 불러온 요약 (불러오기 전 null)
  const [error, setError] = useState<unknown>(null); // 불러오기 오류
  const [productTotal, setProductTotal] = useState<number | null>(null); // 등록한 품목 수 (부족이 0일 때만 묻는다, 모르면 null)
  const [unknownTotal, setUnknownTotal] = useState<number | null>(null); // 판단 불가 품목 수 (품목이 있고 부족이 0일 때만 묻는다)

  useEffect(() => {
    // 처음 열 때 한 번: 요약을 불러오고, 부족이 0일 때만 빈 화면 문구에 필요한 숫자를 더 묻는다
    api<Dashboard>("/dashboard").then(async (d) => {
      setData(d); // 요약 먼저 그린다
      if (d.shortage.count > 0) return; // 부족 품목이 있으면 품목이 있는 게 확실하니 더 묻지 않는다
      try {
        const products = await apiList("/products?page_size=1&include_inactive=true"); // 한 줄만 받아 전체 개수(meta.total)만 본다. 비활성만 있어도 "등록한 품목 있음"
        setProductTotal(products.meta.total); // 0 이면 "첫 품목 등록" 안내
        if (products.meta.total === 0) return; // 품목이 없으면 판단 불가도 0 이라 묻지 않는다
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
  const won = (n: number) => n.toLocaleString(); // 천 단위 쉼표 (예: 1497 → "1,497")

  return (
    <section>
      <h1>대시보드</h1>
      {productTotal === 0 && (
        <p style={S.sectionCard}>아직 등록한 품목이 없습니다. <Link href="/products" style={S.linkButton}>첫 품목 등록</Link></p>
      )}
      {/* 품목이 하나도 없는 회사: 무엇부터 할지 안내 (빈 화면 대신 다음 행동) */}

      <div role="group" aria-label="오늘 확인할 일" style={S.kpiGrid}>
        <NumberCard label="발주 추천" value={`${won(shortage.count)}건`} sub="재고 부족 품목 수와 같습니다" href="/recommendations" more="발주 추천 보기" />
        {/* 1. 지금 발주할 품목 수 (부족 판정과 추천은 같은 계산이라 새로 계산하지 않는다) */}
        <NumberCard label="입고 대기 발주" value={`${won(po.ordered)}건`} sub={`입고 예정 ${won(po.incoming_quantity)}개`} href="/purchase-orders?status=ORDERED" />
        {/* 2. 발주를 보냈고 물건이 들어올 차례인 발주서 */}
        {me?.role === "ADMIN" && (
          <NumberCard label="승인 대기" value={`${won(po.draft)}건`} sub="작성 중인 발주서 (승인은 관리자만)" href="/purchase-orders?status=DRAFT" />
        )}
        {/* 3-관리자: 내가 승인해야 할 발주서 */}
        {me?.role === "STAFF" && (
          <NumberCard label="승인됨" value={`${won(po.approved)}건`} sub="승인되어 발주를 보낼 차례" href="/purchase-orders?status=APPROVED" />
        )}
        {/* 3-담당자: 승인이 나서 공급업체에 보낼 발주서 */}
      </div>

      <h2 style={S.sectionTitle}>진행 중 발주</h2>
      <div style={S.kpiRow4}>
        {/* 타일 4개는 폭이 좁아도 항상 한 줄 (사용자 결정: 부족 품목 표 바로 위) */}
        <NumberCard label="작성 중" value={`${won(po.draft)}건`} href="/purchase-orders?status=DRAFT" />
        <NumberCard label="승인됨" value={`${won(po.approved)}건`} href="/purchase-orders?status=APPROVED" />
        <NumberCard label="발주함" value={`${won(po.ordered)}건`} href="/purchase-orders?status=ORDERED" />
        <NumberCard label="입고 예정 수량" value={`${won(po.incoming_quantity)}개`} sub="발주함 발주서의 아직 안 들어온 수량" href="/purchase-orders?status=ORDERED" />
        {/* 숫자를 누르면 그 상태로 걸러진 발주 목록 (사용자 결정: 표 대신 눌리는 숫자 카드) */}
      </div>

      {/* 항목마다 흰 카드 한 장. 카드 안 제목(h2)은 위 여백을 없앤다 */}
      <div style={S.sectionCard}>
        <h2>재고 부족 품목 ({shortage.count}개)</h2>
        <p style={S.hint}>가용재고(현재고 + 발주 진행 중)가 재주문점 이하인 품목입니다. 발주 추천과 같은 계산입니다.</p>
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
            <div style={S.tableBox}>
              <table style={S.table}>
                <thead>
                  <tr style={S.headRow}>
                    <th>SKU</th><th>품목명</th><th style={S.num}>현재고</th><th style={S.num}>가용재고</th><th style={S.num}>재주문점</th><th style={S.num}>추천 수량</th>
                  </tr>
                </thead>
                <tbody>
                  {shortage.items.map((i) => (
                    <tr key={i.product_id} style={bodyRow(true)}>
                      <td style={S.nowrap}><Link href="/recommendations">{i.sku}</Link></td>
                      {/* 누르면 발주 추천 화면으로 (거기서 초안을 만든다) */}
                      <td>{i.name}</td>
                      <td style={S.num}>{i.current_stock.toLocaleString()}{i.unit}</td>
                      <td style={S.num}>{i.available.toLocaleString()}</td>
                      <td style={S.num}>{fmt(i.reorder_point)}</td>
                      <td style={S.num}>{i.recommended_quantity.toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {shortage.count > shortage.items.length && <p style={S.hint}>최신 품목 {shortage.items.length}개만 보입니다.</p>}
            <p><Link href="/recommendations">발주 추천에서 초안 만들기</Link> · <Link href="/inventory?status=SHORTAGE">재고 현황에서 보기</Link></p>
            {/* 부족 품목에서 발주 작성·재고 현황(부족으로 걸러진 목록)으로 이동 (F7 완료 기준) */}
          </>
        )}
      </div>

      <h2 style={S.sectionTitle}>이번 달 입출고 ({month.month_start} ~ 오늘)</h2>
      <div style={S.kpiGrid}>
        <NumberCard label="입고량" value={`${won(month.in_quantity)}개`} />
        <NumberCard label="출고량" value={`${won(month.out_quantity)}개`} />
        {/* 정정은 원래 이력에서 뺀 순수량, 재고 조정은 제외 (서버 계산 그대로) */}
      </div>

      <div style={S.sectionCard}>
        <h2>과잉재고 ({over.count}개)</h2>
        <p style={S.hint}>현재고가 최근 30일 하루 평균 판매량의 {over.days}일치 이상인 품목입니다. (판매가 없는 품목은 아래 장기재고에서 봅니다)</p>
        {over.count === 0 ? <p style={S.empty}>해당하는 품목이 없습니다.</p> : (
          <>
            <div style={S.tableBox}>
              <table style={S.table}>
                <thead><tr style={S.headRow}><th>SKU</th><th>품목명</th><th style={S.num}>현재고</th><th style={S.num}>일평균 판매</th></tr></thead>
                <tbody>
                  {over.items.map((i) => (
                    <tr key={i.product_id} style={bodyRow(true)}>
                      <td style={S.nowrap}>{i.sku}</td>
                      <td>{i.name}</td>
                      <td style={S.num}>{i.current_stock.toLocaleString()}{i.unit}</td>
                      <td style={S.num}>{fmt(i.avg_daily_sales)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {over.count > over.items.length && <p style={S.hint}>최신 품목 {over.items.length}개만 보입니다.</p>}
          </>
        )}
      </div>

      <div style={S.sectionCard}>
        <h2>장기재고 ({dead.count}개)</h2>
        <p style={S.hint}>재고가 있는데 최근 {dead.days}일 동안 판매가 없는 품목입니다. (첫 입출고가 {dead.days}일 이내인 새 품목은 제외)</p>
        {dead.count === 0 ? (
          <p style={S.empty}>해당하는 품목이 없습니다.</p>
        ) : (
          <>
            <div style={S.tableBox}>
              <table style={S.table}>
                <thead><tr style={S.headRow}><th>SKU</th><th>품목명</th><th style={S.num}>현재고</th><th>마지막 판매일</th></tr></thead>
                <tbody>
                  {dead.items.map((i) => (
                    <tr key={i.product_id} style={bodyRow(true)}>
                      <td style={S.nowrap}>{i.sku}</td>
                      <td>{i.name}</td>
                      <td style={S.num}>{i.current_stock.toLocaleString()}{i.unit}</td>
                      <td>{i.last_sale_date ?? "판매 기록 없음"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {dead.count > dead.items.length && <p style={S.hint}>재고가 많은 {dead.items.length}개만 보입니다. 전체는 <Link href="/inventory">재고 현황</Link>에서 확인하세요.</p>}
          </>
        )}
      </div>
    </section>
  );
}
