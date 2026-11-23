// 안내 챗봇 순수 함수 시험. 실행: npm test (node --test)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { buildHistory, chatReducer, checkSend, errorText, hidesInput, itemsForPath, panelNotice, shouldCloseOnKey, shouldSendOnEnter, sourceHref, type ChatState, type GuideItem, type Turn } from "./chat.ts";

const ans = (ids: string[]) => ({ kind: "ANSWER" as const, answer: "답 글", sources: ids.map((id) => ({ id, title: id, path: null })) });
const turn = (key: number, reply: Turn["reply"]): Turn => ({ key, question: `질문${key}`, reply });

test("buildHistory: 질문과 출처 ID 만 담고 답 글은 없다", () => {
  const h = buildHistory([turn(1, ans(["G-A", "G-B"]))]);
  assert.deepEqual(h, [{ question: "질문1", sources: ["G-A", "G-B"] }]);
  assert.ok(!JSON.stringify(h).includes("답 글"));
});

test("buildHistory: 답을 기다리는 질문(실패해 빠질 질문 포함)은 보내지 않는다", () => {
  assert.deepEqual(buildHistory([turn(1, ans([])), turn(2, null)]), [{ question: "질문1", sources: [] }]);
});

test("buildHistory: 최대 10개", () => {
  const turns = Array.from({ length: 12 }, (_, i) => turn(i + 1, ans([])));
  assert.equal(buildHistory(turns).length, 10);
});

test("checkSend: 빈 글·공백뿐이면 EMPTY", () => {
  assert.equal(checkSend("", 0), "EMPTY");
  assert.equal(checkSend("  \n ", 0), "EMPTY");
  assert.equal(checkSend(" 안녕 ", 0), "OK");
});

test("checkSend: 500자까지 OK, 501자는 TOO_LONG", () => {
  assert.equal(checkSend("가".repeat(500), 0), "OK");
  assert.equal(checkSend("가".repeat(501), 0), "TOO_LONG");
});

test("checkSend: 성공한 질문이 10개 차면 FULL", () => {
  assert.equal(checkSend("질문", 9), "OK");
  assert.equal(checkSend("질문", 10), "FULL");
});

test("errorText: 오류 코드별 문장 표", () => {
  const E = (code: string, details: unknown = null, status = 503) => errorText({ status, code, details });
  const disabled = "지금은 사용법 안내를 쓸 수 없어요. 아래 목차에서 찾아보세요.";
  const daily = "오늘은 사용법 안내를 더 쓸 수 없어요. 내일 다시 쓰거나 목차에서 찾아보세요.";
  assert.equal(E("CHAT_DISABLED"), disabled);
  assert.equal(E("LLM_UNAVAILABLE", { reason: "DISABLED" }), disabled);
  assert.equal(E("CHAT_RATE_LIMITED", { retry_after_seconds: 17 }, 429), "질문이 너무 빨라요. 17초 뒤에 다시 보내 주세요.");
  assert.equal(E("CHAT_RATE_LIMITED", null, 429), "질문이 너무 빨라요. 60초 뒤에 다시 보내 주세요.");
  assert.equal(E("CHAT_DAILY_LIMIT", { limit: 100 }, 429), daily);
  assert.equal(E("LLM_UNAVAILABLE", { reason: "DAILY_LIMIT" }), daily);
  assert.equal(E("LLM_UNAVAILABLE", { reason: "BUDGET" }), daily);
  assert.equal(E("LLM_UNAVAILABLE", { reason: "TIMEOUT" }), "안내 서버가 응답하지 않아요. 잠시 뒤 다시 보내 주세요.");
  assert.equal(E("LLM_UNAVAILABLE", { reason: "UPSTREAM" }), "안내 서버가 응답하지 않아요. 잠시 뒤 다시 보내 주세요.");
  assert.equal(E("LLM_UNAVAILABLE", { reason: "BAD_OUTPUT" }), "답을 만들지 못했어요. 질문을 조금 바꿔 다시 보내 주세요.");
  assert.equal(E("LLM_UNAVAILABLE", { reason: "TOO_LARGE" }), "대화가 너무 길어요. 새 대화를 시작해 주세요.");
  assert.equal(E("VALIDATION_ERROR", null, 422), "대화가 너무 길어요. 새 대화를 시작해 주세요.");
  assert.equal(E("NETWORK_ERROR", null, 0), "서버에 연결할 수 없어요. 인터넷 연결을 확인해 주세요.");
  assert.equal(E("FORBIDDEN", null, 403), "이 기능을 쓸 권한이 없어요.");
  assert.equal(E("UNKNOWN_ERROR", null, 500), "답을 받지 못했어요. 잠시 뒤 다시 보내 주세요.");
  assert.equal(E("LLM_UNAVAILABLE", { reason: "???" }), "답을 받지 못했어요. 잠시 뒤 다시 보내 주세요.");
});

test("errorText: 개인정보 종류를 질문에 든 것만 알려 주고, 이전 대화에만 있으면 새 대화 안내", () => {
  const pii = (details: unknown) => errorText({ status: 422, code: "CHAT_PII_BLOCKED", details });
  assert.equal(pii([{ where: "question", kinds: ["phone"] }]),
    "질문에 전화번호로 보이는 내용이 있어 보내지 않았어요. 그 부분을 지우고 다시 보내 주세요.");
  assert.equal(pii([{ where: "question", kinds: ["rrn", "email", "phone"] }]),
    "질문에 전화번호·이메일 주소·주민등록번호로 보이는 내용이 있어 보내지 않았어요. 그 부분을 지우고 다시 보내 주세요.");
  assert.equal(pii([{ where: "history", index: 2, kinds: ["email"] }]),
    "이전 대화에 개인정보로 보이는 내용이 있어요. 새 대화를 시작해 주세요.");
  assert.match(pii([{ where: "question", kinds: ["email"] }, { where: "history", index: 0, kinds: ["phone"] }]), /^질문에 이메일 주소로/);
});

test("hidesInput: 스위치·LLM 꺼짐만 입력창을 숨긴다", () => {
  assert.equal(hidesInput({ status: 503, code: "CHAT_DISABLED" }), true);
  assert.equal(hidesInput({ status: 503, code: "LLM_UNAVAILABLE", details: { reason: "DISABLED" } }), true);
  assert.equal(hidesInput({ status: 503, code: "LLM_UNAVAILABLE", details: { reason: "TIMEOUT" } }), false);
  assert.equal(hidesInput({ status: 429, code: "CHAT_DAILY_LIMIT" }), false);
});

test("sourceHref: null 은 링크 없음(준비 중), 사이트 안 경로만 링크", () => {
  assert.equal(sourceHref(null), null);
  assert.equal(sourceHref("/purchase-orders"), "/purchase-orders");
});

test("sourceHref: // · http · 역슬래시로 시작하는 주소는 링크가 아니다", () => {
  for (const bad of ["//evil.com", "http://evil.com", "https://evil.com/x", "/\\evil.com", "/\t/evil.com", "/ x", "/a\\b", "/a\nb", "javascript:alert(1)", "dashboard", ""]) {
    assert.equal(sourceHref(bad), null, bad);
  }
});

test("itemsForPath: 현재 화면과 맞는 항목을 최대 3개, 하위 경로도 맞고 path 없는 항목은 뺀다", () => {
  const it = (id: string, path: string | null): GuideItem => ({ id, title: id, path, target: "관리자", status: "사용 가능" });
  const items = [it("A", "/purchase-orders"), it("B", "/purchase-orders"), it("C", null), it("D", "/purchase-orders"), it("E", "/purchase-orders"), it("F", "/products")];
  assert.deepEqual(itemsForPath(items, "/purchase-orders/3").map((i) => i.id), ["A", "B", "D"]);
  assert.deepEqual(itemsForPath(items, "/products").map((i) => i.id), ["F"]);
  assert.deepEqual(itemsForPath(items, "/purchase-orders-x"), []);
});

test("shouldSendOnEnter: Enter 만 전송, Shift+Enter 와 한글 조합 중 Enter 는 전송 안 함", () => {
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: false }), true);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: true, isComposing: false }), false);
  assert.equal(shouldSendOnEnter({ key: "Enter", shiftKey: false, isComposing: true }), false);
  assert.equal(shouldSendOnEnter({ key: "a", shiftKey: false, isComposing: false }), false);
});

test("panelNotice: 입력창이 숨겨지면 오류가 비어도 고정 안내, 아니면 오류가 있을 때만", () => {
  const disabled = errorText({ status: 503, code: "CHAT_DISABLED" });
  assert.equal(panelNotice({ noInput: true, error: "" }), disabled); // 새 대화가 오류를 비워도 안내가 남는다
  assert.equal(panelNotice({ noInput: true, error: disabled }), disabled); // 같은 문장은 한 번만
  assert.equal(panelNotice({ noInput: true, error: "다른 오류" }), disabled);
  assert.equal(panelNotice({ noInput: false, error: "" }), "");
  assert.equal(panelNotice({ noInput: false, error: "다른 오류" }), "다른 오류");
});

test("shouldCloseOnKey: ESC 만 닫고 한글 조합 중 ESC 는 닫지 않는다", () => {
  assert.equal(shouldCloseOnKey({ key: "Escape", isComposing: false }), true);
  assert.equal(shouldCloseOnKey({ key: "Escape", isComposing: true }), false);
  assert.equal(shouldCloseOnKey({ key: "a", isComposing: false }), false);
});

// 챗봇 파일 원문 검사: 대화·질문을 브라우저 저장소나 콘솔에 남기거나 HTML 로 그리는 코드가 없어야 한다
const here = dirname(fileURLToPath(import.meta.url));
const sources = ["chat.ts", "chat-panel.tsx"].map((f) => [f, readFileSync(join(here, f), "utf8")]);

// ----- 대화 상태 전이 표 (chatReducer) -----
// 시작 상태: 답이 온 칸(1), 보내는 중인 칸(2), 오류 줄 있음, 입력 보임. 각 동작이 바꾸는 칸만 바뀌는지 본다
const base = (): ChatState => ({ turns: [turn(1, ans(["G-A"])), turn(2, null)], error: "이전 오류", noInput: false });
const keys = (s: ChatState) => s.turns.map((t) => t.key);

test("전이: SEND_START 는 칸을 붙이고 오류 줄만 비운다 (입력 숨김은 그대로)", () => {
  const s = chatReducer(base(), { type: "SEND_START", key: 3, question: "새 질문" });
  assert.deepEqual(keys(s), [1, 2, 3]);
  assert.deepEqual(s.turns[2], { key: 3, question: "새 질문", reply: null });
  assert.equal(s.error, "");
  assert.equal(s.noInput, false);
  assert.equal(chatReducer({ ...base(), noInput: true }, { type: "SEND_START", key: 3, question: "q" }).noInput, true);
});

test("전이: SEND_OK 는 그 칸에만 답을 붙이고 오류 줄·입력 숨김·다른 칸은 그대로", () => {
  const before = base();
  const s = chatReducer(before, { type: "SEND_OK", key: 2, reply: ans(["G-B"]) });
  assert.deepEqual(s.turns[1].reply, ans(["G-B"]));
  assert.equal(s.turns[0], before.turns[0]); // 다른 칸은 같은 객체 그대로
  assert.equal(s.error, "이전 오류");
  assert.equal(s.noInput, false);
});

test("전이: SEND_OK 가 새 대화 뒤에 오면 아무것도 붙지 않는다", () => {
  const cleared = chatReducer(base(), { type: "NEW_CHAT" });
  assert.deepEqual(chatReducer(cleared, { type: "SEND_OK", key: 2, reply: ans([]) }).turns, []);
});

test("전이: SEND_FAIL 은 그 칸만 빼고 오류 줄을 쓴다 (입력 숨김은 그대로)", () => {
  const s = chatReducer(base(), { type: "SEND_FAIL", key: 2, error: "새 오류" });
  assert.deepEqual(keys(s), [1]);
  assert.equal(s.error, "새 오류");
  assert.equal(s.noInput, false);
});

test("전이: DISABLED 는 그 칸을 빼고 오류 줄을 쓰고 입력창을 숨긴다", () => {
  const s = chatReducer(base(), { type: "DISABLED", key: 2, error: "꺼짐" });
  assert.deepEqual(keys(s), [1]);
  assert.equal(s.error, "꺼짐");
  assert.equal(s.noInput, true);
});

test("전이: NEW_CHAT 은 대화·오류 줄을 비우되 입력 숨김은 남긴다 (꺼짐 안내가 사라지지 않게)", () => {
  const s = chatReducer({ ...base(), noInput: true }, { type: "NEW_CHAT" });
  assert.deepEqual(s, { turns: [], error: "", noInput: true });
  assert.equal(panelNotice(s), errorText({ status: 503, code: "CHAT_DISABLED" })); // 새 대화 뒤에도 꺼짐 안내
});

test("전이: 리듀서는 받은 상태를 고치지 않는다 (새 객체를 돌려준다)", () => {
  const before = base();
  const copy = JSON.stringify(before);
  for (const a of [{ type: "SEND_START", key: 3, question: "q" }, { type: "SEND_OK", key: 2, reply: ans([]) },
    { type: "SEND_FAIL", key: 2, error: "e" }, { type: "DISABLED", key: 2, error: "e" }, { type: "NEW_CHAT" }] as const) {
    chatReducer(before, a);
  }
  assert.equal(JSON.stringify(before), copy);
});

test("정적 검사: 챗봇 파일에 브라우저 저장소 접근이 없다", () => {
  for (const [name, text] of sources) {
    for (const word of ["localStorage", "sessionStorage", "document.cookie", "indexedDB"]) assert.ok(!text.includes(word), `${name}: ${word}`);
  }
});

test("정적 검사: 챗봇 파일에 HTML 직접 삽입·콘솔 출력이 없다", () => {
  for (const [name, text] of sources) {
    for (const word of ["dangerouslySetInnerHTML", "console.", "innerHTML"]) assert.ok(!text.includes(word), `${name}: ${word}`);
  }
});
