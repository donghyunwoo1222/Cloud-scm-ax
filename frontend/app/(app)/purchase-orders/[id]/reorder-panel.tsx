"use client"; // 미리보기를 불러오고 버튼을 누르는 화면이라 브라우저에서 실행

import Link from "next/link"; // 이미 있는 초안으로 가기
import { useRouter } from "next/navigation"; // 새 초안 화면으로 이동
import { useEffect, useState } from "react"; // 미리보기 불러오기

import { api, ApiError } from "../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../lib/list"; // 서버 오류 표시
import { PurchaseOrder } from "../../../lib/po"; // 발주서 모양
import { S } from "../../../lib/styles"; // 화면 공통 스타일
import { useSubmitLock } from "../../../lib/submit-lock"; // 중복 클릭 잠금
import { useToast } from "../../../lib/toast"; // 성공 알림

type Line = { product_id: number; sku: string; name: string; unit: string; quantity: number }; // 원본 줄의 요약 (수량은 원본 재고 단위 수)
type Preview = { supplier_active: boolean; items: Line[]; excluded: Line[]; existing_draft: { id: number; po_number: string } | null }; // GET /reorder

// "이 발주서로 새 초안" 확인 패널 (#188). 미리보기(GET)는 아무것도 바꾸지 않고, 버튼을 눌러야만 POST 로 초안이 만들어진다
export function ReorderPanel({ id, onClose }: { id: string; onClose: () => void }) {
  const router = useRouter(); // 성공하면 새 초안 화면으로
  const toast = useToast(); // 성공 알림
  const { run, busy } = useSubmitLock(); // 연속 클릭은 한 번만 (서버도 업체당 DRAFT 하나로 막는다)
  const [preview, setPreview] = useState<Preview | null>(null); // 복사 미리보기
  const [error, setError] = useState<unknown>(null); // 불러오기·만들기 오류

  useEffect(() => {
    api<Preview>(`/purchase-orders/${id}/reorder`).then(setPreview).catch(setError);
  }, [id]);

  async function create() {
    await run(async () => {
      try {
        const created = await api<PurchaseOrder>(`/purchase-orders/${id}/reorder`, { method: "POST" });
        toast("새 초안을 만들었어요. 단가는 지금 품목 단가예요.");
        router.push(`/purchase-orders/${created.id}`); // 새 초안 화면으로 (이동하면 이 패널도 사라진다)
      } catch (e) {
        setError(e); // DUPLICATE_DRAFT 면 아래에서 기존 초안 링크를 준다
        api<Preview>(`/purchase-orders/${id}/reorder`).then(setPreview).catch(() => {}); // 그사이 바뀐 상태를 다시 읽는다
      }
    });
  }

  const duplicate = error instanceof ApiError && error.code === "DUPLICATE_DRAFT" ? (error.details as { purchase_order_id: number; po_number: string }) : null;
  const draft = preview?.existing_draft ?? (duplicate && { id: duplicate.purchase_order_id, po_number: duplicate.po_number }); // 이미 있는 초안
  const blocked = !!draft || (preview !== null && (!preview.supplier_active || preview.items.length === 0)); // 만들 수 없는 경우

  const q = (n: number) => n.toLocaleString("ko-KR"); // 수량 표시
  const dim = { ...S.hint, margin: 0, fontSize: "var(--text-sm)" } as const; // 흐린 보조 문구
  return (
    <section style={{ ...S.sectionCard, display: "grid", gap: "var(--space-sm)" }} aria-labelledby="reorder-heading">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: "var(--space-sm)" }}>
        <h2 id="reorder-heading" style={{ margin: 0 }}>이 발주서로 새 초안</h2>
        <button type="button" onClick={onClose} disabled={busy}>닫기</button>{/* 보조 버튼: 채우지 않은 기본 모양 */}
      </div>
      {!preview && !error && <p>불러오는 중…</p>}
      {preview && (
        <>
          <p style={{ margin: 0 }}>품목과 수량만 가져와요. 단가·입수·최소 주문량은 지금 품목 정보로 새로 정해요.</p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-xs)", alignItems: "center" }} aria-label="가져오지 않는 것">
            {["납기", "메모", "운송비", "부대비용", "환율"].map((t) => <span key={t} style={{ ...S.statusChip, minHeight: 0, color: "var(--color-muted-foreground)" }}>{t} 제외</span>)}
          </div>
          <p style={dim}>승인 전에는 재고에 영향이 없어요.</p>
          {draft && (
            <div role="status" style={{ borderInlineStart: "4px solid var(--color-warning)", paddingInlineStart: "var(--space-sm)", display: "grid", gap: "var(--space-xs)", justifyItems: "start" }}>
              <p style={{ margin: 0 }}>이 공급업체에 작성 중인 발주서 {draft.po_number} 가 있어요. 새 초안은 업체당 하나만 만들 수 있어요.</p>
              <Link href={`/purchase-orders/${draft.id}`} style={{ display: "inline-flex", alignItems: "center", minHeight: "var(--control-min)", paddingInline: "var(--space-md)", borderRadius: "var(--radius-md, 6px)", background: "var(--color-primary)", color: "var(--color-on-primary)", textDecoration: "none", fontWeight: 600 }}>{/* 이동이지만 이 패널의 주 동작이라 버튼 모양 */}작성 중인 발주서 열기</Link>
            </div>
          )}
          {!preview.supplier_active && <p role="alert" style={S.error}>비활성 공급업체라 새 발주서를 만들 수 없습니다.</p>}
          {preview.items.length > 0 && (
            <div>
              <h3 style={{ margin: "0 0 var(--space-xs)", fontSize: "var(--text-base)" }}>가져올 품목 {preview.items.length}개</h3>
              <table style={{ width: "100%", borderCollapse: "collapse" }} aria-label="가져올 품목">
                <tbody>
                  {preview.items.map((i) => (
                    <tr key={i.product_id}>
                      <td style={{ padding: "var(--space-xs) var(--space-sm)" }}>{i.name} <span style={{ ...S.sub, display: "inline" }}>{i.sku}</span></td>
                      <td style={{ textAlign: "right", whiteSpace: "nowrap", padding: "var(--space-xs) var(--space-sm)" }}>{q(i.quantity)}{i.unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {preview.excluded.length > 0 && (
            <div>
              <h3 style={{ margin: "0 0 var(--space-xs)", fontSize: "var(--text-base)", color: "var(--color-muted-foreground)" }}>제외되는 품목 {preview.excluded.length}개</h3>
              <ul style={{ ...dim, paddingInlineStart: "var(--space-lg)" }}>
                {preview.excluded.map((i) => <li key={i.product_id}>{i.name} {q(i.quantity)}{i.unit} · 비활성 품목</li>)}
              </ul>
            </div>
          )}
          {preview.items.length === 0 && <p role="alert" style={S.error}>가져올 수 있는 활성 품목이 없습니다.</p>}
        </>
      )}
      {!duplicate && <ErrorText error={error} />}
      {!draft && (
        <div style={S.buttons}>
          <button type="button" className="primary-action" disabled={busy || !preview || blocked} onClick={create}>{busy ? "만드는 중…" : "새 초안 만들기"}</button>
        </div>
      )}
    </section>
  );
}
