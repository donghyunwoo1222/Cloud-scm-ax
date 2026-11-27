"use client"; // 메모 접기 상태를 다루므로 브라우저에서 실행

import Link from "next/link"; // 공급업체 링크
import { useEffect, useRef, useState } from "react"; // 메모가 3줄을 넘는지 재는 데 쓴다

import { fmtTime, formatTotal, poProgress, replyLateDays, overdueDays, PurchaseOrder } from "../../../lib/po"; // 발주서 모양·날짜·금액
import { StatusBadge } from "../../../lib/status-badge"; // 납기 지연 배지
import { S } from "../../../lib/styles"; // 화면 공통 스타일

// 요약 카드: 공급업체·약속 납기·합계(원화만) → 진행 단계 한 줄 → 발송·취소 줄. 원가·운송비는 올리지 않는다
export function SummaryCard({ order, today }: { order: PurchaseOrder; today: string }) {
  const delay = overdueDays(order, today); // 서울 오늘 기준 납기 지연
  const steps = poProgress(order); // 승인 → 발주함 → 입고 완료
  const lastDone = steps.map((s) => !!s.iso).lastIndexOf(true); // 마지막으로 끝난 단계 (현재 단계)
  return (
    <div style={S.card}>
      <dl style={S.detailFacts}>
        <div>
          <dt style={S.detailLabel}>공급업체</dt>
          <dd style={S.detailValue}><Link href={`/suppliers/${order.supplier_id}`}>{order.supplier_name}</Link></dd>
        </div>
        <div>
          <dt style={S.detailLabel}>약속 납기</dt>
          <dd style={{ ...S.detailValue, ...S.detailTitle }}>
            {order.due_date ?? "납기 미정"}{/* 약속한 날짜가 없으면 미정으로 표시한다. */}
            {order.supplier_due_date && <span> · 회신 {order.supplier_due_date}{replyLateDays(order) > 0 && ` (${replyLateDays(order)}일 늦음)`}</span>}{/* 회신 납기와 약속과의 차이 */}
            {replyLateDays(order) > 0 && <StatusBadge kind="danger">약속보다 늦은 회신</StatusBadge>}
            {delay > 0 && <StatusBadge kind="danger">납기 {delay.toLocaleString("ko-KR")}일 지연</StatusBadge>}
          </dd>
        </div>
        {order.currency === "KRW" && (
          <div>
            <dt style={S.detailLabel}>발주 금액 합계</dt>
            <dd style={S.detailValue}>{formatTotal(order)}</dd>{/* 표 하단 합계와 같은 함수 */}
          </div>
        )}
        {order.supplier_confirmed_at && (
          <div>
            <dt style={S.detailLabel}>공급업체 확인</dt>
            <dd style={S.detailValue}>{fmtTime(order.supplier_confirmed_at)} <span style={S.hint}>(기록한 사람은 변경 이력에서 확인)</span></dd>{/* 직원도 대신 채울 수 있다 (#265 PR4) */}
          </div>
        )}
      </dl>
      <div style={S.detailMeta}>
        {/* 단계 표시: 끝난 단계는 채운 점, 마지막으로 끝난 단계는 굵게. 날짜는 점 아래 흐린 글자 */}
        <ol aria-label="진행 단계" style={{ display: "flex", margin: 0, padding: 0, listStyle: "none" }}>
          {steps.map((s, i) => (
            <li key={s.label} title={s.iso ? fmtTime(s.iso) : undefined} style={{ flex: i < steps.length - 1 ? "1 1 0" : "0 0 auto", display: "grid", gap: "var(--space-xs)", alignContent: "start", minWidth: 0 }}>
              <span aria-hidden="true" style={{ display: "flex", alignItems: "center" }}>
                <span style={{ width: 12, height: 12, borderRadius: "50%", boxSizing: "border-box", border: "2px solid var(--color-foreground)", background: s.iso ? "var(--color-foreground)" : "transparent", opacity: s.iso ? 1 : 0.35 }} />
                {i < steps.length - 1 && <span style={{ flex: 1, height: 2, background: steps[i + 1].iso ? "var(--color-foreground)" : "var(--color-border)" }} />}
              </span>
              <span style={{ fontWeight: i === lastDone ? 700 : 400, color: s.iso ? "var(--color-foreground)" : "var(--color-muted-foreground)" }}>{s.label}</span>
              {s.date && <span style={S.sub}>{s.date}</span>}
            </li>
          ))}
        </ol>
        {/* 메일 서버로 보낸 시각과 주소. 공급업체가 받았는지는 알 수 없다 */}
        {order.emailed_at && <p style={{ ...S.hint, margin: "var(--space-md) 0 0", fontSize: "var(--text-sm)" }}><span style={{ fontWeight: 600 }}>메일 발송</span> {fmtTime(order.emailed_at)}{order.emailed_to && ` · ${order.emailed_to}`}</p>}
        {order.cancelled_at && <p style={{ margin: "var(--space-xs) 0 0" }}>취소: {fmtTime(order.cancelled_at)}</p>}{/* 취소 사유는 응답에 없어 서버 변경이 필요하다 */}
      </div>
    </div>
  );
}

const row = { display: "grid", gridTemplateColumns: "minmax(5.5rem, 8rem) 1fr", gap: "var(--space-sm)", margin: 0, padding: "var(--space-xs) 0" } as const; // 라벨-값 두 열

// 조건 카드: 납품장소·지불조건·메모. 빈 줄은 만들지 않고 셋 다 비면 카드도 없다
export function ConditionsCard({ order }: { order: PurchaseOrder }) {
  const [open, setOpen] = useState(false); // 메모를 펼쳤는지
  const [long, setLong] = useState(false); // 메모가 3줄을 넘는지
  const memoRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = memoRef.current;
    if (!el || open) return; // 펼친 동안은 다시 재지 않는다 (접으면 다시 잰다)
    const measure = () => setLong(el.scrollHeight > el.clientHeight + 1); // 잘린 만큼 넘치면 긴 메모
    measure();
    window.addEventListener("resize", measure); // 폭이 바뀌면 줄 수도 바뀐다
    return () => window.removeEventListener("resize", measure);
  }, [order.memo, open]);
  if (!order.delivery_address && !order.payment_terms && !order.memo) return null;
  return (
    <section style={S.sectionCard} aria-labelledby="po-conditions-heading">
      <h2 id="po-conditions-heading" style={{ marginTop: 0 }}>조건</h2>
      <dl style={{ margin: 0 }}>
        {order.delivery_address && <div style={row}><dt style={S.detailLabel}>납품장소</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}>{order.delivery_address}</dd></div>}
        {order.payment_terms && <div style={row}><dt style={S.detailLabel}>지불조건</dt><dd style={{ margin: 0, overflowWrap: "anywhere" }}>{order.payment_terms}</dd></div>}
        {order.memo && (
          <div style={row}>
            <dt style={S.detailLabel}>메모</dt>
            <dd style={{ margin: 0, overflowWrap: "anywhere" }}>
              <div ref={memoRef} style={{ whiteSpace: "pre-wrap", ...(open ? {} : { display: "-webkit-box", WebkitLineClamp: 3, WebkitBoxOrient: "vertical", overflow: "hidden" }) }}>{order.memo}</div>
              {(long || open) && <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} style={{ marginTop: "var(--space-xs)" }}>{open ? "접기" : "더 보기"}</button>}
            </dd>
          </div>
        )}
      </dl>
    </section>
  );
}
