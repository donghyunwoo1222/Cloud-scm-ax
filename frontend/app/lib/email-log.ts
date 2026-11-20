// 메일 발송 이력 (GET /purchase-orders/{id}/email-log, #182). 서버 EmailLogOut 과 칸 이름이 같다 (사람은 이름만, 번호·이메일 없음)
export type EmailLog = {
  id: number; // 이력 번호
  kind: string; // ORDER(발주서) / REMINDER(독촉)
  to_address: string; // 받는 주소 (전체)
  sent_by_name: string; // 보낸 사람 이름 (없으면 빈 글자)
  result: string; // SENT / FAILED / UNSAVED
  failure_code: string | null; // FAILED 일 때만: AUTH, RECIPIENT_REFUSED, TIMEOUT, CONNECTION, OTHER
  with_link: boolean; // 회신 링크 포함 여부 (화면에는 쓰지 않는다)
  created_at: string; // 시도 시각 (ISO)
};

// 종류 → 이름 (예: "ORDER" → "발주서"). 모르는 값은 서버 글자 그대로
export const KIND_LABEL: Record<string, string> = { ORDER: "발주서", REMINDER: "독촉" };
export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind;

// 실패 코드 → 사용자 문장. 어조는 서버 po_mail.failure() 와 맞춘다. 모르는 코드는 OTHER 문장
const FAILURE_TEXT: Record<string, string> = {
  AUTH: "메일 서버 로그인에 실패했습니다.",
  RECIPIENT_REFUSED: "메일 서버가 받는 주소를 거부했습니다.",
  TIMEOUT: "메일 서버가 시간 안에 응답하지 않았습니다.",
  CONNECTION: "메일 서버에 연결하지 못했습니다.",
  OTHER: "발송 중 오류가 났습니다.",
};

// 결과 → 한 줄 문장. 예) FAILED + AUTH → "실패: 메일 서버 로그인에 실패했습니다."
export function resultText(row: Pick<EmailLog, "result" | "failure_code">): string {
  if (row.result === "SENT") return "성공";
  if (row.result === "UNSAVED") return "메일은 나갔으나 기록 저장에 실패했습니다";
  return `실패: ${FAILURE_TEXT[row.failure_code ?? ""] ?? FAILURE_TEXT.OTHER}`; // FAILED (모르는 result 도 실패 문장으로 보수적으로)
}
