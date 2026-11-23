import { fmtTime } from "./po.ts"; // 서울 시각 (다음 가능 시각 표시)

// GET /purchase-orders/{id}/reminder 응답 (#269). 서버 build_preview 와 칸 이름이 같다
export type ReminderPreview = {
  to: string | null; // 받는 사람 (없으면 null)
  supplier_id: number;
  reply_to: string; // 답장 받을 주소 = 지금 보내는 사람
  subject: string;
  intro: string; // 기본 앞머리 (사용자가 고칠 수 있는 유일한 부분)
  fixed_html: string; // 고정 부분 (남은 품목표 포함, 서버가 escape 함)
  with_link: boolean; // 새 확인 링크가 들어가는지
  mail_ready: boolean; // 메일 서버 설정이 있는지
  sent_count: number; max_per_order: number; last_sent_at: string | null; next_allowed_at: string | null;
  blocked: "REMINDER_LIMIT" | "REMINDER_TOO_SOON" | "REMINDER_DAILY_LIMIT" | null; // 한도에 걸린 이유
};

export const REMINDER_INTRO_MAX = 2000; // 앞머리 최대 글자 수 (서버 ReminderSend.intro 와 같은 값)

// 오류 모양 (ApiError 와 같은 칸). ApiError 를 직접 import 하면 node 테스트가 api.ts 를 읽어야 해서 칸만 받는다
type Err = { status: number; code: string; message: string; details?: unknown };

const detail = (e: Err, key: string) => (e.details as Record<string, unknown> | null)?.[key]; // details 에서 값 하나

// 오류 코드 → 사용자 문장. 서버 원문은 MAIL_FAILED(서버가 쓴 문장)만 쓰고 나머지는 화면이 정한 문장이다
export function reminderErrorText(e: Err): string {
  switch (e.code) {
    case "REMINDER_DISABLED": return "독촉 메일 기능이 꺼져 있습니다. 관리자에게 문의하세요.";
    case "MAIL_NOT_CONFIGURED": return "메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요.";
    case "INVALID_STATUS": return "발주함 상태의 발주서만 독촉 메일을 보낼 수 있습니다. 화면을 새로 고쳐 상태를 확인해 주세요.";
    case "NOT_OVERDUE": return "납기가 지나지 않았거나 아직 도착하지 않은 품목이 없어 독촉 메일을 보낼 수 없습니다.";
    case "NO_SUPPLIER_EMAIL": return "공급업체 이메일이 없어 보낼 수 없습니다. 공급업체 정보에 이메일을 넣어 주세요.";
    case "REMINDER_LIMIT": {
      const limit = detail(e, "limit");
      return `이 발주에는 독촉 메일을 이미 ${typeof limit === "number" ? `${limit}번` : "최대 횟수만큼"} 보냈습니다. 더 보낼 수 없습니다.`;
    }
    case "REMINDER_TOO_SOON": {
      const at = detail(e, "next_allowed_at");
      return `마지막 독촉 뒤 시간이 충분히 지나지 않았습니다.${typeof at === "string" ? ` ${fmtTime(at)} 이후에 다시 보낼 수 있습니다.` : " 잠시 뒤에 다시 보내 주세요."}`;
    }
    case "REMINDER_DAILY_LIMIT": return "오늘 보낼 수 있는 독촉 메일 수를 다 썼습니다. 내일 다시 보내 주세요.";
    case "MAIL_FAILED": return e.message || "메일을 보내지 못했습니다. 다시 시도해도 됩니다. 발주서는 바뀌지 않았습니다."; // 서버가 쓴 문장 (다시 시도 가능 안내가 들어 있다)
    case "MAIL_SENT_NOT_SAVED": return "독촉 메일은 보냈지만 발송 기록을 저장하지 못했습니다. 다시 보내지 말고 공급업체에 도착했는지 확인해 주세요.";
  }
  if (e.status === 404) return "발주서를 찾을 수 없습니다.";
  if (e.status === 401 || e.status === 403) return "이 작업을 할 권한이 없습니다.";
  if (e.status >= 500) return "서버에 문제가 생겨 독촉 메일을 보내지 못했습니다. 잠시 뒤 이력을 확인한 다음 다시 시도해 주세요.";
  return "독촉 메일을 처리하지 못했습니다. 화면을 새로 고친 뒤 다시 시도해 주세요.";
}

// 미리보기의 blocked 칸 → 버튼 옆 안내 문장 (한도에 걸리지 않았으면 빈 글자)
export function blockedText(p: Pick<ReminderPreview, "blocked" | "max_per_order" | "next_allowed_at">): string {
  if (!p.blocked) return "";
  return reminderErrorText({ status: 409, code: p.blocked, message: "", details: { limit: p.max_per_order, next_allowed_at: p.next_allowed_at } });
}

// 독촉 패널을 열어 둘지. openFor = 사용자가 버튼을 눌러 연 발주서 id(없으면 null).
// 지금 보는 발주서가 아니거나 서버가 remind 를 막았으면 닫힌 것이다 (닫히면 패널이 사라져 앞머리 글도 함께 비워진다)
export const reminderPanelOpen = (openFor: string | null, id: string, canRemind: boolean) => openFor !== null && openFor === id && canRemind;

// 패널의 오류 상태. 발송 오류(sendError)와 미리보기 불러오기 오류(loadError)를 따로 둬서, 다시 불러오기가 발송 오류를 지우지 못하게 한다
export type PanelErrors = { sendError: string; loadError: string; unsaved: boolean }; // unsaved: 메일은 나갔는데 기록 저장 실패 → 다시 보내기 금지
export const NO_ERRORS: PanelErrors = { sendError: "", loadError: "", unsaved: false };
export type PanelEvent =
  | { type: "load-ok" } // 미리보기 불러오기 성공: 불러오기 오류만 지운다
  | { type: "load-fail"; text: string }
  | { type: "send-start" } // 사용자가 확인창을 수락해 발송을 시작: 이전 발송 오류를 지운다
  | { type: "send-fail"; text: string; code?: string }
  | { type: "close" }; // 패널이 닫힘: 모두 비운다

export function panelErrors(state: PanelErrors, ev: PanelEvent): PanelErrors {
  switch (ev.type) {
    case "load-ok": return { ...state, loadError: "" };
    case "load-fail": return { ...state, loadError: ev.text };
    case "send-start": return { ...state, sendError: "" }; // unsaved 는 유지 (이미 나간 메일, 버튼이 잠겨 있어 보통 오지 않는다)
    case "send-fail": return { ...state, sendError: ev.text, unsaved: state.unsaved || ev.code === "MAIL_SENT_NOT_SAVED" };
    case "close": return NO_ERRORS;
  }
}
