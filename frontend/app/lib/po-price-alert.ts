// 발주서 단가 변동 경고 (#283)의 순수 함수. 화면(po-form.tsx)은 이 둘만 부른다.
// 서버가 문장을 만든다. 여기서는 퍼센트·방향을 계산하지 않는다.

export type PriceLine = { product_id: string; unit_price: string; box: boolean }; // 폼 줄 중 필요한 칸
export type PriceAnswer = { product_id: number; unit_price: number | null; alert: { message: string } | null }; // 서버 응답 한 줄

const MAX_LINES = 2000; // 서버 줄 수 상한 (MAX_ORDER_LINES)
const MAX_PRICE = 100_000_000; // 서버 단가 상한(1억)

// 응답 보관·조회에 쓰는 열쇠. 입력이 바뀌면 열쇠가 달라져 옛 경고는 저절로 안 보인다
export const priceKey = (supplierId: string, productId: string | number, unitPrice: string | number) => `${supplierId}:${Number(productId)}:${Number(unitPrice)}`;

// 확인 대상 줄: 재고 단위 줄(박스 아님) + 품목 선택 + 0 이상 정수 단가(상한 이하). 예) "1250" 대상, "" · "12.5" · "-3" · "100000001" 은 제외
const target = (l: PriceLine) => !l.box && /^[1-9]\d*$/.test(l.product_id) && /^\d+$/.test(l.unit_price) && Number(l.unit_price) <= MAX_PRICE;

// 요청 본문. 공급업체가 없거나 대상 줄이 없으면 null(호출하지 않는다). 줄이 여러 개여도 한 번에 담는다
export function priceCheckBody(supplierId: string, lines: PriceLine[]) {
  if (!/^\d+$/.test(supplierId)) return null;
  const items = lines.filter(target).slice(0, MAX_LINES).map((l) => ({ product_id: Number(l.product_id), unit_price: Number(l.unit_price) }));
  return items.length ? { supplier_id: Number(supplierId), items } : null;
}

// 응답을 열쇠로 보관할 모양으로 바꾼다 (경고 없는 줄은 뺀다)
export function keepAlerts(supplierId: string, answers: PriceAnswer[]): Record<string, string> {
  return Object.fromEntries(answers.flatMap((a) => (a.alert && a.unit_price != null ? [[priceKey(supplierId, a.product_id, a.unit_price), a.alert.message]] : [])));
}

// 지금 줄의 열쇠와 일치할 때만 문장을 돌려준다. 대상이 아닌 줄(박스 등)은 항상 null
export function pickAlert(alerts: Record<string, string>, supplierId: string, line: PriceLine): string | null {
  return target(line) ? alerts[priceKey(supplierId, line.product_id, line.unit_price)] ?? null : null;
}

// 화면에 보일 문장: 요청을 보내지 않는 상태(enabled=false, 외화 발주)에서는 이미 받아 둔 경고도 숨긴다
export const visibleAlert = (alerts: Record<string, string>, supplierId: string, line: PriceLine, enabled: boolean) =>
  enabled ? pickAlert(alerts, supplierId, line) : null;
