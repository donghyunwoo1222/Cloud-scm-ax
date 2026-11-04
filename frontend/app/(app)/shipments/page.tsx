"use client"; // 폼 부품을 쓰는 화면

import { MovementForm } from "../../lib/movement-form"; // 입출고 등록 폼

// 출고 등록 화면 (주소 /shipments): 판매·폐기·기타 출고와 실사 조정
export default function Page() {
  return (
    <section>
      <h1>출고 등록</h1>
      <MovementForm types={["SALE", "DISPOSAL", "OTHER_OUT", "ADJUSTMENT"]} />
    </section>
  );
}
