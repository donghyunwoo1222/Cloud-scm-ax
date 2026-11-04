"use client"; // 주소의 번호를 읽고 서버에서 불러오는 화면

import Link from "next/link"; // 상세 화면으로 돌아가는 링크
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, useEffect, useState } from "react"; // 처음 한 번 실행, 상태

import { api } from "../../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../../lib/list"; // 서버 오류 표시
import { PurchaseOrder } from "../../../../lib/po"; // 발주서 모양
import { PoForm } from "../../../../lib/po-form"; // 발주서 작성·수정 폼

// 발주서 수정 화면 (주소 /purchase-orders/번호/edit): 작성 중(DRAFT)일 때만 연다
function Detail() {
  const { id } = useParams<{ id: string }>(); // 주소의 발주서 번호
  const [order, setOrder] = useState<PurchaseOrder | null>(null); // 불러온 발주서
  const [error, setError] = useState<unknown>(null); // 불러오기 오류

  useEffect(() => {
    api<PurchaseOrder>(`/purchase-orders/${id}`).then(setOrder).catch(setError); // 서버에서 발주서 한 건
  }, [id]);

  return (
    <section>
      <h1>발주서 수정{order && ` · ${order.po_number}`}</h1>
      <ErrorText error={error} />
      {order && order.status !== "DRAFT" && (
        <p>작성 중(DRAFT)인 발주서만 수정할 수 있습니다. <Link href={`/purchase-orders/${order.id}`}>상세로 돌아가기</Link></p>
      )}
      {/* DRAFT 가 아니면 폼을 열지 않는다 (서버도 409 INVALID_STATUS 로 막는다) */}
      {order && order.status === "DRAFT" && <PoForm order={order} />}
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
