// 공급업체 확인 화면(#265)의 순수 함수 모음: 화면 분기, 오류 문구, 날짜 범위. 날짜 계산은 이 파일 한 곳에서만 한다.

// 서버 공개 응답 (supplier-document-fields.md 5절)
export type ReplyState = "REPLYABLE" | "RECEIVED" | "RECEIVED_CLOSED" | "CANCELLED";
export type ReplyView = {
  state: ReplyState; notice: string | null; can_reply: boolean; replies_left: number | null;
  po_number: string | null; buyer_name: string | null; order_date: string | null; due_date: string | null;
  supplier_due_date: string | null; supplier_confirmed_at: string | null;
  items: { name: string; options: string | null; quantity: number; unit: string | null }[];
};

export type Screen = "FIRST" | "RECONFIRM" | "EXHAUSTED" | "NOTICE";

// 어떤 화면을 그릴지: FIRST=처음 확인, RECONFIRM=이미 확인(납기만 다시), EXHAUSTED=회신 횟수 소진, NOTICE=서버 안내만(입고 완료·취소)
export function screenOf(r: Pick<ReplyView, "state" | "can_reply" | "replies_left" | "supplier_confirmed_at">): Screen {
  if (r.state !== "REPLYABLE") return "NOTICE";
  if (!r.can_reply || (r.replies_left ?? 0) <= 0) return "EXHAUSTED"; // 날짜 입력·버튼을 숨긴다
  return r.supplier_confirmed_at ? "RECONFIRM" : "FIRST";
}

export const EXHAUSTED_NOTICE = "회신 횟수를 모두 사용했습니다. 납기를 더 바꾸려면 메일로 답장해 주세요.";
export const SUBMIT_LABEL: Record<"FIRST" | "RECONFIRM", string> = { FIRST: "확인하고 보내기", RECONFIRM: "납기 회신 보내기" };

// 서버 오류 code → 화면 문구. LIMIT 은 서버 문장을 그대로 쓴다
export function errorMessage(code: string, serverMessage: string): string {
  switch (code) {
    case "SUPPLIER_LINK_INVALID": return "링크가 만료되었거나 더 이상 쓸 수 없습니다. 담당자에게 새 링크를 요청해 주세요.";
    case "SUPPLIER_REPLY_LIMIT": return `${serverMessage} 메일로 답장해 주세요.`;
    case "SUPPLIER_REPLY_CLOSED": return "취소되었거나 입고 완료된 발주라 더 이상 회신할 수 없습니다.";
    case "VALIDATION_ERROR": return "납기는 오늘부터 1년 이내의 날짜로 골라 주세요.";
    case "NETWORK_ERROR": return "서버에 연결할 수 없습니다. 잠시 뒤 다시 시도해 주세요.";
    default: return "처리하지 못했습니다. 잠시 뒤 다시 시도해 주세요.";
  }
}

// 납기 입력의 선택 범위 = 서버 규칙(서울 오늘 ~ 1년 뒤, 2/29 는 2/28). 예) 2028-02-29 → max 2029-02-28
export function dateRange(now: Date = new Date()): { min: string; max: string } {
  const min = now.toLocaleDateString("sv-SE", { timeZone: "Asia/Seoul" }); // YYYY-MM-DD
  const [y, m, d] = min.split("-").map(Number);
  const day = m === 2 && d === 29 ? 28 : d; // 다음 해에는 2/29 가 없다
  return { min, max: `${y + 1}-${String(m).padStart(2, "0")}-${String(day).padStart(2, "0")}` };
}

// 확인창 문구 (날짜를 골랐으면 납기, 아니면 확인만)
export const confirmText = (date: string, left: number): string =>
  date
    ? `회신 납기를 ${date}로 보냅니다. 납기는 앞으로 ${left - 1}번 더 바꿀 수 있습니다. 보낼까요?`
    : "이 발주를 확인했다고 알립니다. 보낼까요?";
