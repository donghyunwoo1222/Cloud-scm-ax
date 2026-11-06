"use client"; // 폼 부품을 쓰는 화면

import { useSearchParams } from "next/navigation"; // 재고 화면에서 보낸 유형을 읽는다.
import { Suspense } from "react"; // 주소를 읽는 부분만 브라우저에서 그린다.
import { MovementForm } from "../../lib/movement-form"; // 입출고 등록 폼

// 출고 등록 화면 (주소 /shipments): 판매·폐기·기타 출고와 실사 조정
function ShipmentForm() {
  const initialType = useSearchParams().get("type") === "ADJUSTMENT" ? "ADJUSTMENT" : "SALE";
  return (
    <section>
      <h1>출고 등록</h1>
      <MovementForm key={initialType} initialType={initialType} types={["SALE", "DISPOSAL", "OTHER_OUT", "ADJUSTMENT"]} />
    </section>
  );
}

export default function Page() {
  return <Suspense fallback={<p>불러오는 중…</p>}><ShipmentForm /></Suspense>;
}
