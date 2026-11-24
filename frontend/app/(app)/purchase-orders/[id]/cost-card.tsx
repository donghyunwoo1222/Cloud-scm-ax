// 발주서 상세의 "원가" 카드 (#267, 내부 전용): 공급업체 문서·메일에는 나가지 않는다. 값은 모두 서버 cost 묶음을 그대로 보여 준다.
import { FX_ENABLED } from "../../../lib/config"; // 외화 화면 스위치
import { PurchaseOrder } from "../../../lib/po"; // 발주서 모양
import { CURRENCIES, formatFxText, freightLabel, formatWon, FREIGHT_TERMS, rateUnitLabel } from "../../../lib/po-fx"; // 통화 이름·표시
import { S } from "../../../lib/styles"; // 화면 공통 스타일

const MISSING_NAME: Record<string, string> = { exchange_rate: "환율", freight: "운송비" }; // 미입력 항목 이름

// 외화 발주의 원화 환산 한 줄 (총액 칸 아래): 승인 전에는 "예상", 승인 뒤에는 고정값
export function KrwConversion({ order }: { order: PurchaseOrder }) {
  if (order.currency === "KRW") return null; // 원화 발주는 환산이 없다
  const { goods_krw: krw } = order.cost;
  if (krw === null) return <span style={S.sub}>원화 환산: 환율 미입력</span>;
  return <span style={S.sub}>원화 환산{order.krw_goods_total === null ? "(예상)" : "(승인 때 고정)"} {formatWon(krw)}원</span>;
}

export function CostCard({ order }: { order: PurchaseOrder }) {
  const { cost, currency } = order;
  const fx = currency !== "KRW";
  const fixed = order.krw_goods_total !== null; // 승인 때 고정된 값인지 (아니면 예상)
  const won = (n: number | null, empty = "-") => (n === null ? empty : `${formatWon(n)}원`);
  return (
    <section aria-labelledby="cost-heading" style={S.sectionCard}>
      <h2 id="cost-heading" style={{ marginTop: 0 }}>원가 <span style={S.hint}>(내부용, 공급업체 문서·메일에는 나가지 않습니다)</span></h2>
      <dl className="info-strip">
        {FX_ENABLED && <div><dt>통화</dt><dd>{CURRENCIES[currency].label}</dd></div>}
        {fx && <div><dt>환율 ({rateUnitLabel(currency)})</dt><dd>{order.exchange_rate ?? "미입력"}{order.exchange_rate && (fixed ? " (승인 때 고정)" : " (승인 전, 바뀔 수 있음)")}</dd></div>}
        {fx && <div><dt>품목 외화 합계</dt><dd>{cost.goods_fx_total != null ? `${formatFxText(cost.goods_fx_total, currency)} ${currency}` : "-"}</dd></div>}
        <div><dt>품목 원화 합계</dt><dd>{won(cost.goods_krw, "환율 미입력")}{fx && cost.goods_krw !== null && (fixed ? " (고정)" : " (예상)")}</dd></div>
        <div><dt>운송비</dt><dd>{[order.freight_terms ? FREIGHT_TERMS[order.freight_terms] ?? order.freight_terms : "", freightLabel(cost.freight)].filter(Boolean).join(" · ")}</dd></div>
        <div><dt>부대비용 합계</dt><dd>{formatWon(cost.extras_total)}원</dd></div>
        <div><dt>원가 (부가세 제외)</dt><dd><strong>{won(cost.total)}</strong></dd></div>
        {cost.received_total !== null && (
          <div><dt>입고 기준 원가</dt><dd>{won(cost.received_total)} <span style={S.hint}>(품목은 입고 수량만큼 {won(cost.received_goods_krw)}, 운송비·부대비용은 전액)</span></dd></div>
        )}
      </dl>
      {order.extra_costs.length > 0 && (
        <ul style={{ margin: "var(--space-xs) 0 0", paddingLeft: "1.2em" }}>
          {order.extra_costs.map((e, i) => <li key={i}>{e.name}: {formatWon(e.amount)}원</li>)}
        </ul>
      )}
      {cost.missing.length > 0 && <p role="status" style={S.hint}>아직 입력하지 않은 항목: {cost.missing.map((m) => MISSING_NAME[m] ?? m).join(", ")}</p>}
      {order.special_terms && <p style={{ whiteSpace: "pre-wrap" }}>특약: {order.special_terms}</p>}
      {fx && (order.status === "APPROVED" || order.status === "ORDERED") && <p style={S.hint}>환율을 잘못 넣었으면 취소 후 새로 작성하세요. 승인한 뒤에는 환율을 고칠 수 없습니다.</p>}
    </section>
  );
}
