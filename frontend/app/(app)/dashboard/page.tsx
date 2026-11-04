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
};
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

  const { purchase_orders: po, month, dead_stock: dead } = data; // 이름 줄이기
  const noData = po.draft + po.approved + po.ordered === 0 && month.in_quantity + month.out_quantity === 0 && dead.count === 0; // 보여줄 숫자가 모두 0

  return (
    <section>
      <h1>대시보드</h1>
      {noData && <p>아직 데이터가 없습니다. <Link href="/products">품목 등록</Link>부터 시작해 보세요.</p>}
      {/* 데이터가 없으면 품목 등록 안내 (service-planning.md 화면 정의) */}

      <h2 style={S.sectionTitle}>재고 부족 품목</h2>
      <p>부족 품목은 발주 추천 계산(6주차) 뒤에 표시됩니다.</p>
      {/* 부족·과잉 기준은 추천 공식(#38·#39)과 한 곳에서 계산하려고 이번에는 자리만 둔다 */}

      <h2 style={S.sectionTitle}>진행 중 발주</h2>
      <table style={S.table}>
        <thead><tr style={S.headRow}><th>작성 중</th><th>승인됨</th><th>발주함</th><th>입고 예정 수량</th></tr></thead>
        <tbody>
          <tr style={S.row}>
            <td>{po.draft}건</td>
            <td>{po.approved}건</td>
            <td>{po.ordered}건</td>
            <td>{po.incoming_quantity.toLocaleString()}개</td>
            {/* 입고 예정 = 발주함(ORDERED) 발주의 아직 안 들어온 수량 합계 */}
          </tr>
        </tbody>
      </table>
      <p><Link href="/purchase-orders">발주 화면으로</Link></p>

      <h2 style={S.sectionTitle}>이번 달 입출고 ({month.month_start} ~ 오늘)</h2>
      <table style={S.table}>
        <thead><tr style={S.headRow}><th>입고 수량</th><th>출고 수량</th></tr></thead>
        <tbody>
          <tr style={S.row}>
            <td>{month.in_quantity.toLocaleString()}개</td>
            <td>{month.out_quantity.toLocaleString()}개</td>
            {/* 정정은 원래 이력에서 뺀 순수량, 재고 조정은 제외 */}
          </tr>
        </tbody>
      </table>

      <h2 style={S.sectionTitle}>장기재고 ({dead.count}개)</h2>
      <p>재고가 있는데 최근 {dead.days}일 동안 판매가 없는 품목입니다. (첫 입출고가 {dead.days}일 이내인 새 품목은 제외)</p>
      {dead.count === 0 ? (
        <p>해당하는 품목이 없습니다.</p>
      ) : (
        <>
          <table style={S.table}>
            <thead><tr style={S.headRow}><th>SKU</th><th>품목명</th><th>현재고</th><th>마지막 판매일</th></tr></thead>
            <tbody>
              {dead.items.map((i) => (
                <tr key={i.product_id} style={bodyRow(true)}>
                  <td>{i.sku}</td>
                  <td>{i.name}</td>
                  <td>{i.current_stock.toLocaleString()}{i.unit}</td>
                  <td>{i.last_sale_date ?? "판매 기록 없음"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {dead.count > dead.items.length && <p>재고가 많은 {dead.items.length}개만 보입니다. 전체는 <Link href="/inventory">재고 현황</Link>에서 확인하세요.</p>}
        </>
      )}
    </section>
  );
}
