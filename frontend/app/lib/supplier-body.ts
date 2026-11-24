// 공급업체 폼 값 → 서버로 보낼 본문 (순수 함수: 폼과 시험이 같은 함수를 쓴다)
export type SupplierForm = {
  name: string; lead_time_days: string; contact_name: string; phone: string; email: string; payment_terms: string; memo: string;
  default_currency: string; default_freight_terms: string; default_special_terms: string;
};

// 빈 선택 칸은 null(비우기), 리드타임은 숫자로 (검사는 서버가 한다: 음수·소수는 422).
// 외화 스위치가 꺼져 있으면 default_currency 키를 본문에서 아예 뺀다: 수정할 때 기존 기본 통화(예: USD)를 덮어쓰지 않고, 새로 등록하면 서버 기본값 KRW 가 된다.
export function supplierBody(form: SupplierForm, fxEnabled: boolean) {
  return {
    name: form.name, // 업체명 (앞뒤 공백은 서버가 지운다)
    lead_time_days: form.lead_time_days === "" ? null : Number(form.lead_time_days), // "5" → 5, 비우면 null(→ 서버가 422)
    contact_name: form.contact_name || null,
    phone: form.phone || null,
    email: form.email || null,
    payment_terms: form.payment_terms || null,
    memo: form.memo || null,
    ...(fxEnabled ? { default_currency: form.default_currency } : {}),
    default_freight_terms: form.default_freight_terms || null, // 선택 안 함 → 미설정(null)
    default_special_terms: form.default_special_terms.trim() || null,
  };
}
