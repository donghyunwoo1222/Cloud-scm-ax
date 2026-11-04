"use client"; // 폼 부품을 쓰는 화면

import { PoForm } from "../../../lib/po-form"; // 발주서 작성·수정 폼

// 발주서 작성 화면 (주소 /purchase-orders/new)
export default function Page() {
  return (
    <section>
      <h1>발주서 작성</h1>
      <p>공급업체마다 작성 중인 발주서는 하나만 둘 수 있습니다.</p>
      <PoForm />
    </section>
  );
}
