"use client"; // 서버에서 불러온 요약을 상태로 그리는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주·재고 화면 링크
import { useEffect, useState } from "react"; // 처음 한 번 실행, 상태

import { api } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../lib/list"; // 서버 오류 문장
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

// 대시보드 화면 (주소 /dashboard): 로그인 후 시작 화면
export default function Page() {
  const [data, setData] = useState<Dashboard | null>(null); // 불러온 요약 (불러오기 전 null)
  const [error, setError] = useState<unknown>(null); // 불러오기 오류

  useEffect(() => {
    api<Dashboard>("/dashboard").then(setData).catch(setError); // 처음 열 때 한 번
  }, []);

  if (error) return <section><h1>대시보드</h1><ErrorText error={error} /></section>; // 오류면 문장만
  if (!data) return <section><h1>대시보드</h1><p>불러오는 중…</p></section>; // 불러오기 전

  const { purchase_orders: po, month, dead_stock: dead, shortage, overstock: over } = data; // 이름 줄이기
  const noData = po.draft + po.approved + po.ordered === 0 && month.in_quantity + month.out_quantity === 0
    && dead.count + shortage.count + over.count === 0; // 보여줄 숫자가 모두 0

  return (
    <section>
      <h1>대시보드</h1>
      {noData && <p>아직 데이터가 없습니다. <Link href="/products">품목 등록</Link>부터 시작해 보세요.</p>}
      {/* 데이터가 없으면 품목 등록 안내 (service-planning.md 화면 정의) */}

      {/* 항목마다 흰 카드 한 장. 카드 안 제목(h2)은 위 여백을 없앤다 */}
      <div style={S.sectionCard}>
        <h2>재고 부족 품목 ({shortage.count}개)</h2>
        <p style={S.hint}>가용재고(현재고 + 발주 진행 중)가 재주문점 이하인 품목입니다. 발주 추천과 같은 계산입니다.</p>
        {shortage.count === 0 ? <p style={S.empty}>해당하는 품목이 없습니다.</p> : (
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
                      <td><Link href="/recommendations">{i.sku}</Link></td>
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
            <p><Link href="/recommendations">발주 추천에서 초안 만들기</Link> · <Link href="/inventory">재고 현황 (상태: 부족으로 거르기)</Link></p>
            {/* 부족 품목에서 발주 작성·재고 현황으로 이동 (F7 완료 기준) */}
          </>
        )}
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
                      <td>{i.sku}</td>
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
        <h2>진행 중 발주</h2>
        <div style={S.tableBox}>
          <table style={S.table}>
            <thead><tr style={S.headRow}><th style={S.num}>작성 중</th><th style={S.num}>승인됨</th><th style={S.num}>발주함</th><th style={S.num}>입고 예정 수량</th></tr></thead>
            <tbody>
              <tr style={S.row}>
                <td style={S.num}>{po.draft}건</td>
                <td style={S.num}>{po.approved}건</td>
                <td style={S.num}>{po.ordered}건</td>
                <td style={S.num}>{po.incoming_quantity.toLocaleString()}개</td>
                {/* 입고 예정 = 발주함(ORDERED) 발주의 아직 안 들어온 수량 합계 */}
              </tr>
            </tbody>
          </table>
        </div>
        <p><Link href="/purchase-orders">발주 화면으로</Link></p>
      </div>

      <div style={S.sectionCard}>
        <h2>이번 달 입출고 ({month.month_start} ~ 오늘)</h2>
        <div style={S.tableBox}>
          <table style={S.table}>
            <thead><tr style={S.headRow}><th style={S.num}>입고 수량</th><th style={S.num}>출고 수량</th></tr></thead>
            <tbody>
              <tr style={S.row}>
                <td style={S.num}>{month.in_quantity.toLocaleString()}개</td>
                <td style={S.num}>{month.out_quantity.toLocaleString()}개</td>
                {/* 정정은 원래 이력에서 뺀 순수량, 재고 조정은 제외 */}
              </tr>
            </tbody>
          </table>
        </div>
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
                      <td>{i.sku}</td>
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
