"use client"; // 주소의 번호를 읽고 서버에서 불러오는 화면

import Link from "next/link"; // 목록·발주서 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, useEffect, useState } from "react"; // 처음 한 번 실행, 상태

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText, Pager, useList } from "../../../lib/list"; // 목록 공통 부품
import { fmtDate, PurchaseOrder, STATUS_LABEL } from "../../../lib/po"; // 발주서 모양·상태 이름·날짜 표시
import { StatusBadge } from "../../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/suppliers/{id} 중 이 화면이 쓰는 칸
type Supplier = { id: number; name: string; lead_time_days: number; contact_name: string | null; phone: string | null; email: string | null; is_active: boolean };

// 공급업체 상세 화면 (주소 /suppliers/번호): 업체 정보 + 발주 이력(약속 납기·단가·실제 입고일)
function Detail() {
  const { id } = useParams<{ id: string }>(); // 주소의 공급업체 번호
  const [supplier, setSupplier] = useState<Supplier | null>(null); // 불러온 업체
  const [error, setError] = useState<unknown>(null); // 불러오기 오류
  const list = useList<PurchaseOrder>("/purchase-orders", { supplier_id: id }); // 이 업체의 발주서만 (20개씩, 최신순)

  useEffect(() => {
    api<Supplier>(`/suppliers/${id}`).then(setSupplier).catch(setError); // 서버에서 업체 한 건
  }, [id]);

  return (
    <section>
      <h1>공급업체{supplier && ` · ${supplier.name}`}</h1>
      <p><Link href="/suppliers">목록</Link></p>
      <ErrorText error={error} />
      {supplier && (
        <p>
          리드타임 {supplier.lead_time_days}일 · 담당자 {supplier.contact_name ?? "-"} · 연락처 {supplier.phone ?? "-"} · 이메일 {supplier.email ?? "-"} · {supplier.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}
        </p>
      )}

      <h2 style={S.sectionTitle}>발주 이력</h2>
      <ErrorText error={list.error} />
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>발주번호</th><th>상태</th><th>품목</th><th style={S.num}>발주 수량</th><th style={S.num}>단가(원)</th><th>약속 납기</th><th>실제 입고일</th></tr>
        </thead>
        <tbody>
          {list.rows.flatMap((o) =>
            o.items.map((i, index) => (
              <tr key={i.id} style={index === 0 ? S.row : undefined}>
                {/* 발주서 첫 줄에만 구분선·발주 정보를 보인다 (단가는 줄마다 다르다) */}
                <td>{index === 0 ? <Link href={`/purchase-orders/${o.id}`}>{o.po_number}</Link> : ""}</td>
                <td>{index === 0 ? STATUS_LABEL[o.status] : ""}</td>
                <td>{i.product_sku} · {i.product_name}</td>
                <td style={S.num}>{i.quantity}</td>
                <td style={S.num}>{i.unit_price}</td>
                <td style={S.nowrap}>{index === 0 ? (o.due_date ?? "-") : ""}</td>
                <td style={S.nowrap}>{index === 0 ? fmtDate(o.received_at) : ""}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
      </div>
      {list.meta?.total === 0 && <p style={S.empty}>이 공급업체의 발주 이력이 없습니다.</p>}
      {/* 빈 목록 안내 */}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}

// 주소의 번호는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (Next.js 가 빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <Detail />
    </Suspense>
  );
}
