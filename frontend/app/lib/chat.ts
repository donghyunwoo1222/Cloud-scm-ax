// 안내 챗봇(#199) 화면의 순수 함수와 타입. React·브라우저 저장소를 쓰지 않아 node --test 로 바로 시험한다.
// 서버 계약: backend/app/api/chat.py, schemas/chat.py, services/chat_guide.py

export const MAX_QUESTION = 500; // 질문 글자 수 상한 (서버 스키마와 같다)
export const MAX_TURNS = 10; // 이전 대화로 서버에 보낼 수 있는 질문 수 상한 (서버 history 상한과 같다)

// GET /chat/guide/toc 의 항목 하나
export type GuideItem = { id: string; title: string; path: string | null; target: string; status: string };
// GET /chat/guide/toc 응답
export type Toc = { enabled: boolean; items: GuideItem[] };
// 답에 붙는 출처. path 는 서버가 안내서의 "화면:" 줄로 만든 값이고 null 이면 아직 화면이 없다
export type Source = { id: string; title: string; path: string | null };
// POST /chat/guide 응답
export type Answer = { kind: "ANSWER" | "NOT_FOUND" | "DATA_QUESTION"; answer: string; sources: Source[] };
// 화면 목록의 대화 한 칸. reply 가 null 이면 아직 답을 기다리는 중("보내는 중…")
export type Turn = { key: number; question: string; reply: Answer | null };
// 서버에 보내는 이전 대화 한 칸: 질문과 출처 ID 만 (답 글은 절대 보내지 않는다)
export type HistoryTurn = { question: string; sources: string[] };

// 이전 대화 만들기: 답이 온 질문만, 질문 글과 출처 ID 만 담는다. 실패해 목록에서 빠진 질문과 대기 중인 질문은 없다
// 예) [성공 A(출처 G-PO), 대기 B] → [{question:"A", sources:["G-PO"]}]
export function buildHistory(turns: Turn[]): HistoryTurn[] {
  return turns
    .filter((t) => t.reply !== null) // 답이 온 것만
    .map((t) => ({ question: t.question, sources: (t.reply?.sources ?? []).map((s) => s.id) })) // 답 글은 버린다
    .slice(-MAX_TURNS); // 안전장치: 화면이 10개에서 입력을 막으므로 보통은 잘리지 않는다
}

export type SendCheck = "OK" | "EMPTY" | "TOO_LONG" | "FULL"; // 보낼 수 있으면 OK, 아니면 이유

// 보낼 수 있는지: 공백뿐이면 EMPTY, 앞뒤 공백을 뺀 길이가 500자 초과면 TOO_LONG, 성공한 질문이 10개 찼으면 FULL
export function checkSend(text: string, doneCount: number): SendCheck {
  if (doneCount >= MAX_TURNS) return "FULL"; // 새 대화를 시작해야 한다
  const trimmed = text.trim(); // 서버도 앞뒤 공백을 뺀 뒤 길이를 센다
  if (trimmed.length === 0) return "EMPTY";
  if (trimmed.length > MAX_QUESTION) return "TOO_LONG";
  return "OK";
}

// Enter 로 전송할지: Shift+Enter 는 줄바꿈, 한글 조합 중 Enter 는 글자 확정이라 전송하지 않는다
export function shouldSendOnEnter(e: { key: string; shiftKey: boolean; isComposing: boolean }): boolean {
  return e.key === "Enter" && !e.shiftKey && !e.isComposing;
}

// 출처 링크 고르기: 사이트 안 경로("/" 로 시작, "//"·"/\" 로 시작하지 않음)만 링크로 쓴다. 그 밖(null·http 주소 등)은 링크 없음
export function sourceHref(path: string | null): string | null {
  if (!path || !path.startsWith("/") || path.startsWith("//") || path.startsWith("/\\")) return null;
  return path;
}

// 목차 항목의 "물어보기" 질문 글. 예) "발주서 승인" → "발주서 승인 방법을 알려 주세요"
export const askText = (title: string) => `${title} 방법을 알려 주세요`;

// 이 화면 안내: 현재 화면 경로와 맞는 목차 항목을 최대 3개 (같은 경로가 여럿이면 앞에서부터 3개)
// 예) pathname "/purchase-orders/3" 는 path "/purchase-orders" 항목과 맞는다 (사이드 메뉴의 현재 화면 표시와 같은 규칙)
export function itemsForPath(items: GuideItem[], pathname: string): GuideItem[] {
  return items
    .filter((i) => i.path !== null && (pathname === i.path || pathname.startsWith(`${i.path}/`)))
    .slice(0, 3);
}

// 개인정보 종류 이름. 서버가 details 로 주는 값: email / phone / rrn (backend chat_guide._PII)
const PII_NAME: [string, string][] = [["phone", "전화번호"], ["email", "이메일 주소"], ["rrn", "주민등록번호"]];

// 서버가 준 PII 위치 목록(details)에서 "질문"에 든 종류 이름을 모은다. 예) [{where:"question",kinds:["phone"]}] → ["전화번호"]
function piiNames(details: unknown, where: "question" | "history"): string[] {
  if (!Array.isArray(details)) return [];
  const kinds = new Set<string>();
  for (const d of details) {
    if (d && d.where === where && Array.isArray(d.kinds)) d.kinds.forEach((k: unknown) => kinds.add(String(k)));
  }
  return PII_NAME.filter(([kind]) => kinds.has(kind)).map(([, name]) => name);
}

type ErrorLike = { status: number; code: string; details?: unknown }; // ApiError 와 같은 칸 (테스트에서 객체로 흉내 낸다)

const DISABLED = "지금은 사용법 안내를 쓸 수 없어요. 아래 목차에서 찾아보세요.";
const DAILY = "오늘은 사용법 안내를 더 쓸 수 없어요. 내일 다시 쓰거나 목차에서 찾아보세요.";
const TOO_LONG = "대화가 너무 길어요. 새 대화를 시작해 주세요.";

// 서버 오류 → 화면 문장. 서버 원문과 사유 코드는 화면에 내보내지 않는다
export function errorText(e: ErrorLike): string {
  const reason = (e.details as { reason?: string } | null)?.reason; // LLM_UNAVAILABLE 의 사유
  switch (e.code) {
    case "CHAT_DISABLED":
      return DISABLED;
    case "CHAT_RATE_LIMITED": {
      const wait = (e.details as { retry_after_seconds?: unknown } | null)?.retry_after_seconds;
      return `질문이 너무 빨라요. ${typeof wait === "number" ? wait : 60}초 뒤에 다시 보내 주세요.`;
    }
    case "CHAT_PII_BLOCKED": {
      const names = piiNames(e.details, "question");
      if (names.length === 0 && piiNames(e.details, "history").length > 0) {
        return "이전 대화에 개인정보로 보이는 내용이 있어요. 새 대화를 시작해 주세요."; // 이전 질문에만 있으면 질문을 지워도 소용없다
      }
      return `질문에 ${names.length ? names.join("·") : "개인정보"}로 보이는 내용이 있어 보내지 않았어요. 그 부분을 지우고 다시 보내 주세요.`;
    }
    case "CHAT_DAILY_LIMIT":
      return DAILY;
    case "LLM_UNAVAILABLE":
      if (reason === "DISABLED") return DISABLED;
      if (reason === "DAILY_LIMIT" || reason === "BUDGET") return DAILY; // 회사 상한과 월 예산을 구분하지 않는다
      if (reason === "TIMEOUT" || reason === "UPSTREAM") return "안내 서버가 응답하지 않아요. 잠시 뒤 다시 보내 주세요.";
      if (reason === "BAD_OUTPUT") return "답을 만들지 못했어요. 질문을 조금 바꿔 다시 보내 주세요.";
      if (reason === "TOO_LARGE") return TOO_LONG;
      break; // 모르는 사유는 아래 공통 처리
    case "VALIDATION_ERROR":
      return TOO_LONG;
    case "NETWORK_ERROR":
      return "서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.";
  }
  if (e.status === 0) return "서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.";
  if (e.status === 403) return "이 기능을 쓸 권한이 없어요.";
  return "답을 받지 못했어요. 잠시 뒤 다시 보내 주세요.";
}

// 아래 칸에 보여 줄 안내 문장: 입력창이 숨겨졌으면(noInput) 오류 줄과 상관없이 항상 고정 안내(오류가 같은 문장이어도 한 번만),
// 아니면 오류가 있을 때만 그 문장. 예) {noInput:true, error:""} → DISABLED, {noInput:false, error:""} → ""
export function panelNotice(s: { noInput: boolean; error: string }): string {
  return s.noInput ? DISABLED : s.error;
}

// 이 오류가 오면 입력창을 숨기고 목차만 보여 줄지 (스위치 꺼짐·LLM 꺼짐)
export function hidesInput(e: ErrorLike): boolean {
  return e.code === "CHAT_DISABLED" || (e.code === "LLM_UNAVAILABLE" && (e.details as { reason?: string } | null)?.reason === "DISABLED");
}
