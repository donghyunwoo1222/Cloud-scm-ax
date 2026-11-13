"use client"; // 주소의 번호를 읽고 서버에서 불러오는 화면

import Link from "next/link"; // 목록·발주서 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, useEffect, useState } from "react"; // 처음 한 번 실행, 상태
import { useToast } from "../../../lib/toast"; // 성공 알림 토스트

import { api } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText, Pager, useList } from "../../../lib/list"; // 목록 공통 부품
import { skuWithOptions } from "../../../lib/options"; // 품목 옵션 요약
import { fmtDate, formatOrderUnitPrice, PurchaseOrder, STATUS_LABEL } from "../../../lib/po"; // 발주서 모양·상태 이름·날짜·단가 표시
import { StatusBadge } from "../../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/suppliers/{id} 중 이 화면이 쓰는 칸
type Supplier = { id: number; name: string; lead_time_days: number; contact_name: string | null; phone: string | null; email: string | null; payment_terms: string | null; is_active: boolean };

// 공급업체 상세 화면 (주소 /suppliers/번호): 업체 정보 + 발주 이력(약속 납기·단가·실제 입고일)
function Detail() {
  const { id } = useParams<{ id: string }>(); // 주소의 공급업체 번호
  const [supplier, setSupplier] = useState<Supplier | null>(null); // 불러온 업체
  const [error, setError] = useState<unknown>(null); // 불러오기 오류
  const list = useList<PurchaseOrder>("/purchase-orders", { supplier_id: id }); // 이 업체의 발주서만 (20개씩, 최신순)

  useEffect(() => {
    api<Supplier>(`/suppliers/${id}`).then(setSupplier).catch(setError); // 서버에서 업체 한 건
  }, [id]);

  // 비활성·다시 활성은 목록 표가 아니라 이 상세 화면에서만 한다 (잘못 누르기 어렵게)
  const toast = useToast(); // 성공 알림 토스트
  async function setActive(s: Supplier, active: boolean) {
    if (!active && !window.confirm(`${s.name}을 비활성화할까요? 새 발주에서는 제외되며 기존 이력은 남습니다.`)) return;
    try {
      setSupplier(await api<Supplier>(`/suppliers/${s.id}`, { method: "PATCH", body: { is_active: active } })); // 바뀐 업체로 다시 그린다 (삭제는 없다)
      setError(null);
      toast(active ? "공급업체를 다시 활성화했어요" : "공급업체를 비활성화했어요");
    } catch (e) {
      setError(e);
    }
  }

  return (
    <section>
      <div style={S.detailHeader}>
        <h1>공급업체{supplier && ` · ${supplier.name}`}</h1>
        {supplier && <div style={S.buttons}>
          <Link href={`/suppliers?edit=${supplier.id}`} style={S.linkButtonGhost}>수정</Link>{/* 목록 화면의 수정 폼을 이 업체로 연다 */}
          <button type="button" onClick={() => setActive(supplier, !supplier.is_active)}>{supplier.is_active ? "비활성" : "다시 활성"}</button>
        </div>}
      </div>
      <p style={S.hint}><Link href="/suppliers">공급업체 목록</Link></p>
      <ErrorText error={error} />
      {supplier && (
        <dl className="info-strip">
          {/* 한 줄 줄글 대신 이름·값 칸. 비어 있는 값은 "-" */}
          <div><dt>리드타임</dt><dd>{supplier.lead_time_days}일</dd></div>
          <div><dt>담당자</dt><dd>{supplier.contact_name ?? "-"}</dd></div>
          <div><dt>연락처</dt><dd>{supplier.phone ?? "-"}</dd></div>
          <div><dt>이메일</dt><dd>{supplier.email ?? "-"}</dd></div>
          <div><dt>지불조건</dt><dd>{supplier.payment_terms ?? "-"}</dd></div>
          <div><dt>상태</dt><dd>{supplier.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}</dd></div>
        </dl>
      )}

      <h2 style={S.sectionTitle}>발주 이력</h2>
      <ErrorText error={list.error} />
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}><th>발주번호</th><th>상태</th><th>품목</th><th style={S.num}>발주 수량</th><th style={S.num}>단가(원)</th><th>약속 납기</th><th>입고 완료일</th></tr>
        </thead>
        <tbody>
          {list.rows.flatMap((o) =>
            o.items.map((i, index) => (
              <tr key={i.id} style={index === 0 ? S.row : undefined}>
                {/* 발주서 첫 줄에만 구분선·발주 정보를 보인다 (단가는 줄마다 다르다) */}
                <td>{index === 0 ? <Link href={`/purchase-orders/${o.id}`}>{o.po_number}</Link> : ""}</td>
                <td>{index === 0 ? (o.status === "ORDERED" && o.items.some((i) => i.received_quantity > 0) ? "부분 입고" : STATUS_LABEL[o.status]) : ""}</td>
                <td><span style={S.nowrap}>{skuWithOptions(i.product_sku, i)}</span> · {i.product_name}</td>
                <td style={S.num}>{i.quantity}</td>
                <td style={S.num}>{formatOrderUnitPrice(i)}</td>
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
