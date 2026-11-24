// 재고 화면의 짧은 안내 문장을 만드는 순수 함수 (화면 파일에서 떼어 표 테스트로 검증한다)

const count = (n: number, unit: string) => `${n.toLocaleString("ko-KR")}${unit}`; // 쉼표 + 단위 (예: 1,200개)

// 입출고 수량을 넣었을 때의 변동 미리보기. 예) (IN, 18, 1) → "현재 18 → 19개"
// 수량이 1 이상 정수가 아니면 null (보여 주지 않는다). 출고가 현재고보다 많으면 음수 대신 경고 문장
export function previewStock(direction: "IN" | "OUT", current: number, qty: number, unit = "개"): string | null {
  if (!Number.isSafeInteger(qty) || qty < 1 || !Number.isSafeInteger(current)) return null;
  const after = direction === "IN" ? current + qty : current - qty; // 입고는 더하고 출고는 뺀다
  if (!Number.isSafeInteger(after)) return null; // 정수 한도를 넘는 큰 수는 보여 주지 않는다 (서버가 판단)
  if (after < 0) return `재고보다 많이 출고하려고 해요 (현재 ${count(current, unit)})`;
  return `현재 ${current.toLocaleString("ko-KR")} → ${count(after, unit)}`;
}

// 부족 안내 문장. 예) (SHORTAGE, 가용 8, 재주문점 20) → "재주문점보다 12개 모자라요"
// 부족이 아니거나 값이 없으면 null. 재주문점은 소수일 수 있어 올림해 정수로 말한다 (예: 20.2 − 8 → 13개)
export function shortageText(status: string | null, available: number, reorderPoint: number | null, unit = "개"): string | null {
  if (status !== "SHORTAGE" || reorderPoint == null || !Number.isFinite(reorderPoint)) return null;
  const gap = Math.ceil(reorderPoint - available); // 모자란 수량
  return gap >= 1 ? `재주문점보다 ${count(gap, unit)} 모자라요` : null; // 같거나 넘으면(소수 오차) 문장 없음
}

// 현재고 숫자 색 종류: 품절(0)은 soldout, 부족은 shortage, 그 밖은 normal
export function stockTone(status: string | null, current: number): "soldout" | "shortage" | "normal" {
  if (current === 0) return "soldout";
  return status === "SHORTAGE" ? "shortage" : "normal";
}

// 실사 조정 사유 빠른 칩 (프론트 상수 — 서버는 자유 문장으로 받는다)
export const REASON_CHIPS = ["재고 조사 보정", "파손", "분실", "유통기한 폐기", "반품 입고"] as const;
