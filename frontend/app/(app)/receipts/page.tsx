"use client"; // 폼 부품을 쓰는 화면

import Link from "next/link"; // 기존 발주 대기 목록으로 연결한다
import { MovementForm } from "../../lib/movement-form"; // 입출고 등록 폼
import { S } from "../../lib/styles"; // 공통 카드와 버튼 모양

// 입고 종류를 먼저 구분해 발주 입고가 직접 입고 이력으로 남는 실수를 줄인다.
export default function Page() {
  return (
    <section>
      <h1>입고 등록</h1>
      <div style={S.kpiGrid}>
        <section style={S.card}>
          <h2>발주 입고</h2>
          <p>발주서와 도착한 품목·수량을 대조합니다.</p>
          <p style={{ marginTop: "var(--space-sm)" }}><Link href="/purchase-orders?status=ORDERED" style={S.linkButton}>입고 대기 발주 보기</Link></p>
        </section>
        <section style={S.card}>
          <h2>직접 입고</h2>
          <p>반품처럼 연결할 발주서가 없는 물건을 등록합니다.</p>
          <p style={{ marginTop: "var(--space-sm)" }}><a href="#direct-receipt" style={S.linkButtonGhost}>직접 입고 입력</a></p>
        </section>
      </div>
      <h2 id="direct-receipt" tabIndex={-1} style={S.sectionTitle}>직접 입고 입력</h2>
      <MovementForm types={["RECEIPT"]} />
    </section>
  );
}
