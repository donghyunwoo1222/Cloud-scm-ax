import Link from "next/link"; // 화면 안 이동

// 실사 조정 폼을 여는 주소. 재고 현황 버튼과 입출고 등록 화면의 안내 링크가 같은 것을 쓴다.
export const ADJUSTMENT_HREF = "/shipments?type=ADJUSTMENT";

// "재고 숫자가 실제와 다른가요?" 안내 링크 (이미 실사 조정 모드인 화면에서는 쓰지 않는다)
export function AdjustLink() {
  return <p style={{ margin: "var(--space-xs) 0" }}>재고 숫자가 실제와 다른가요? <Link href={ADJUSTMENT_HREF}>실사 조정하기</Link></p>;
}
