// 발주서 상세의 "원가" 카드 (#267, 내부 전용): 공급업체 문서·메일에는 나가지 않는다. 값은 모두 서버 cost 묶음을 그대로 보여 준다.
import { FX_ENABLED } from "../../../lib/config"; // 외화 화면 스위치
import { PurchaseOrder } from "../../../lib/po"; // 발주서 모양
import { CURRENCIES, formatFxText, freightLabel, formatWon, RECEIVED_COST_NOTE, rateUnitLabel, termsToShow } from "../../../lib/po-fx"; // 통화 이름·표시
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
      <h2 id="cost-heading" style={{ marginTop: 0, marginBottom: "var(--space-xs)" }}>원가</h2>
      <p style={{ ...S.hint, margin: 0 }}>(내부용, 공급업체 문서·메일에는 나가지 않습니다)</p>
      <dl className="info-strip flat">
        {FX_ENABLED && <div><dt>통화</dt><dd>{CURRENCIES[currency].label}</dd></div>}
        {fx && <div><dt>환율 ({rateUnitLabel(currency)})</dt><dd>{order.exchange_rate ?? "미입력"}{order.exchange_rate && (fixed ? " (승인 때 고정)" : " (승인 전, 바뀔 수 있음)")}</dd></div>}
        {fx && <div><dt>품목 외화 합계</dt><dd>{cost.goods_fx_total != null ? `${formatFxText(cost.goods_fx_total, currency)} ${currency}` : "-"}</dd></div>}
        <div><dt>품목 원화 합계</dt><dd>{won(cost.goods_krw, "환율 미입력")}{fx && cost.goods_krw !== null && (fixed ? " (고정)" : " (예상)")}</dd></div>
        <div><dt>운송비</dt><dd>{freightLabel(cost.freight)}</dd></div>
        <div><dt>부대비용 합계</dt><dd>{formatWon(cost.extras_total)}원</dd></div>
        <div><dt>원가 (부가세 제외)</dt><dd><strong>{won(cost.total)}</strong></dd></div>
        {cost.received_total !== null && (
          <div><dt>입고 기준 원가</dt><dd>{won(cost.received_total)} <span style={S.hint}>({RECEIVED_COST_NOTE})</span></dd></div>
        )}
      </dl>
      {order.extra_costs.length > 0 && (
        <>
          <h3 style={{ margin: "var(--space-md) 0 var(--space-xs)", fontSize: "var(--text-base)" }}>부대비용 내역</h3>
          <ul style={{ margin: "0 0 var(--space-md)", paddingLeft: "1.2em" }}>
            {order.extra_costs.map((e, i) => <li key={i}>{e.name}: {formatWon(e.amount)}원</li>)}
          </ul>
        </>
      )}
      {cost.missing.length > 0 && <p role="status" style={{ ...S.hint, margin: "var(--space-sm) 0" }}>아직 입력하지 않은 항목: {cost.missing.map((m) => MISSING_NAME[m] ?? m).join(", ")}</p>}
      {fx && (order.status === "APPROVED" || order.status === "ORDERED") && <p style={S.hint}>환율을 잘못 넣었으면 취소 후 새로 작성하세요. 승인한 뒤에는 환율을 고칠 수 없습니다.</p>}
    </section>
  );
}

// 운송조건·특약 구역 (원가 카드 밖): 공급업체 문서에 표시되는 값. 둘 다 없으면 아무것도 그리지 않는다
export function TermsSection({ order }: { order: PurchaseOrder }) {
  const t = termsToShow(order.freight_terms, order.special_terms);
  if (!t) return null;
  return (
    <section aria-labelledby="terms-heading" style={S.sectionCard}>
      <h2 id="terms-heading" style={{ marginTop: 0 }}>운송조건·특약 <span style={S.hint}>(공급업체 문서에 표시됩니다)</span></h2>
      <dl className="info-strip flat stack">
        {t.freight && <div><dt>운송조건</dt><dd>{t.freight}</dd></div>}
        {t.special && <div><dt>특약</dt><dd style={{ whiteSpace: "pre-wrap" }}>{t.special}</dd></div>}
      </dl>
    </section>
  );
}
