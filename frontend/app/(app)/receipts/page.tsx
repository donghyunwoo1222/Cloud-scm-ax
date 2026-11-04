"use client"; // 폼 부품을 쓰는 화면

import { MovementForm } from "../../lib/movement-form"; // 입출고 등록 폼

// 입고 등록 화면 (주소 /receipts): 발주 없는 직접 입고만. 발주 입고는 #36
export default function Page() {
  return (
    <section>
      <h1>입고 등록</h1>
      <p>발주 없이 들어온 물건(반품 등)을 직접 입고합니다. 발주 입고는 발주 화면 작업(#36)에서 추가됩니다.</p>
      <MovementForm types={["RECEIPT"]} />
    </section>
  );
}
