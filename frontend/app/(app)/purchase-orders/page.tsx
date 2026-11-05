"use client"; // 목록·필터를 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 상세·작성 화면 링크
import { useSearchParams } from "next/navigation"; // 주소의 ?status= 읽기 (대시보드 숫자를 누르면 걸러진 채로 열기)
import { Suspense, useEffect, useState } from "react"; // 주소 읽는 부품 감싸기, 처음 한 번 실행, 상태

import { apiList } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { PurchaseOrder, STATUS_LABEL, totalQuantity } from "../../lib/po"; // 발주서 모양·상태 이름·수량 합계
import { S } from "../../lib/styles"; // 화면 공통 스타일

type SupplierOption = { id: number; name: string }; // 거르기 선택 상자에 쓸 공급업체

// 발주 화면 (주소 /purchase-orders): 최신순 목록 + 상태·공급업체로 거르기
// 주소의 ?status= 는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (Next.js 가 빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <PurchaseOrders />
    </Suspense>
  );
}

// 주소의 status 를 읽어 목록 부품에 넘긴다. key 를 status 로 주어, 화면이 열린 채(Next.js 가 보관한 화면) 다른 status 링크로 다시 들어와도
// 목록 부품을 새로 만들어 초기값이 다시 적용되게 한다 (useState 초기값은 처음 만들 때 한 번만 쓰인다)
function PurchaseOrders() {
  const asked = useSearchParams().get("status") ?? ""; // 주소로 받은 상태 (예: ?status=ORDERED → "ORDERED")
  const initial = Object.keys(STATUS_LABEL).includes(asked) ? asked : ""; // 발주 상태 5개만 초기값으로 쓰고 그 밖은 무시("" 이면 전체)
  return <PurchaseOrdersBody key={initial} initialStatus={initial} />; // status 가 바뀔 때만 새로 만든다 (화면 안에서 필터를 바꾸는 건 주소를 안 바꾸므로 그대로)
}

function PurchaseOrdersBody({ initialStatus }: { initialStatus: string }) {
  const [status, setStatus] = useState(initialStatus); // 고른 상태 ("" 이면 전체). 처음 값은 주소에서
  const [supplierId, setSupplierId] = useState(""); // 고른 공급업체 ("" 이면 전체)
  const [suppliers, setSuppliers] = useState<SupplierOption[]>([]); // 공급업체 선택지
  const [error, setError] = useState<unknown>(null); // 선택지 불러오기 오류
  const list = useList<PurchaseOrder>("/purchase-orders", { status, supplier_id: supplierId }); // 20개씩, 최신순, 조건이 바뀌면 다시 불러온다

  useEffect(() => {
    // 비활성 업체가 낸 지난 발주서도 걸러 볼 수 있게 비활성도 포함한다
    // shortcut: 업체 100개까지만 불러온다(서버 page_size 최대). 100개를 넘으면 검색형 선택 상자로 바꾼다
    apiList<SupplierOption>("/suppliers?page_size=100&include_inactive=true").then((r) => setSuppliers(r.data)).catch(setError);
  }, []);

  // 조건을 바꾸면 1쪽부터 다시 본다
  function filter(set: (value: string) => void, value: string) {
    set(value); // 조건 바꾸기
    list.setPage(1); // 1쪽으로
  }

  return (
    <section>
      <h1>발주</h1>
      <p><Link href="/purchase-orders/new" style={S.linkButton}>발주서 작성</Link></p>

      <div style={S.toolbar}>
        <label>상태
          <select value={status} onChange={(e) => filter(setStatus, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {Object.entries(STATUS_LABEL).map(([code, label]) => <option key={code} value={code}>{label}</option>)}
          </select>
        </label>
        <label>공급업체
          <select value={supplierId} onChange={(e) => filter(setSupplierId, e.target.value)} style={S.block}>
            <option value="">전체</option>
            {suppliers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
      </div>
      <ErrorText error={error} />
      <ErrorText error={list.error} />

      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>발주번호</th><th>공급업체</th><th>상태</th><th style={S.num}>품목 수</th><th style={S.num}>합계 수량</th><th>약속 납기</th></tr>
        </thead>
        <tbody>
          {list.rows.map((o) => (
            <tr key={o.id} style={S.row}>
              <td style={S.nowrap}><Link href={`/purchase-orders/${o.id}`}>{o.po_number}</Link></td>
              <td>{o.supplier_name}</td>
              <td style={S.nowrap}>{STATUS_LABEL[o.status]}</td>
              <td style={S.num}>{o.items.length}</td>
              <td style={S.num}>{totalQuantity(o)}</td>
              <td style={S.nowrap}>{o.due_date ?? "-"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {list.meta?.total === 0 && <p style={S.empty}>조건에 맞는 발주서가 없습니다.</p>}
      {/* 빈 목록 안내 */}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
