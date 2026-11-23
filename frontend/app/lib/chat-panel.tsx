"use client"; // 입력·전송·목록을 브라우저에서 처리

import Link from "next/link"; // 출처·목차의 화면 이동 링크
import { usePathname } from "next/navigation"; // 지금 화면 경로 ("이 화면 안내")
import { KeyboardEvent, useEffect, useRef, useState } from "react"; // 상태·포커스·스크롤

import { ApiError, api } from "./api"; // 공통 API 호출 함수
import { Answer, GuideItem, MAX_QUESTION, Turn, askText, buildHistory, checkSend, errorText, hidesInput, itemsForPath, panelNotice, shouldCloseOnKey, shouldSendOnEnter, sourceHref } from "./chat"; // 순수 함수와 타입
import { useSubmitLock } from "./submit-lock"; // 전송 중 연타 잠금

// 안내 챗봇 패널. 대화는 이 컴포넌트의 React 상태(메모리)에만 있다: 새로고침하면 사라지고, 닫아도(hidden) 유지되고, 화면을 옮겨도 유지된다
// (패널을 감싼 (app) 레이아웃이 계속 떠 있어서). 질문·답 글은 어디에도 저장하거나 기록하지 않는다
export function ChatPanel({ items, open, onClose, onNavigate, closeRef }: {
  items: GuideItem[]; // 목차 (레이아웃이 한 번 받아 온 것)
  open: boolean; // 열려 있는지 (닫히면 숨기기만 한다)
  onClose: () => void; // 닫기 버튼·ESC
  onNavigate: () => void; // 출처·목차 링크로 이동할 때 (모바일 시트는 여기서 닫는다)
  closeRef: React.RefObject<HTMLButtonElement | null>; // 닫기 버튼 (입력창이 없을 때 포커스를 받는다)
}) {
  const pathname = usePathname(); // 예) /purchase-orders/3
  const lock = useSubmitLock(); // 전송 중 잠금: 연타해도 1번
  const [turns, setTurns] = useState<Turn[]>([]); // 대화 목록 (답을 기다리는 질문 포함)
  const [text, setText] = useState(""); // 입력 중인 글
  const [error, setError] = useState(""); // 오류 줄 (없으면 빈 글자)
  const [noInput, setNoInput] = useState(false); // 스위치·LLM 이 꺼져 입력창을 숨길지 (목차는 계속 보인다)
  const [tocOpen, setTocOpen] = useState(true); // 목차 펼침 (대화를 시작하면 접는다)
  const seq = useRef(0); // 대화 칸 번호
  const input = useRef<HTMLTextAreaElement>(null); // 입력창 (열면 포커스)
  const body = useRef<HTMLDivElement>(null); // 스크롤 영역 (새 답이 오면 아래로)
  const toc = useRef<HTMLDetailsElement>(null); // 목차 ("목차 보기" 버튼이 여기로 옮긴다)

  const doneCount = turns.filter((t) => t.reply !== null).length; // 답이 온 질문 수
  const verdict = checkSend(text, doneCount); // 보낼 수 있는지
  const full = doneCount >= 10 && !noInput; // 10개 차면 입력 대신 새 대화 안내

  useEffect(() => {
    if (open) (input.current ?? closeRef.current)?.focus(); // 열면 입력창으로, 입력창이 없으면 닫기 버튼으로
  }, [open, closeRef, noInput, full]);

  useEffect(() => {
    if (body.current && turns.length > 0) body.current.scrollTop = body.current.scrollHeight; // 새 질문·답이 보이게 아래로
  }, [turns]);

  // 질문 하나를 보낸다. fromInput 은 입력창의 글을 보내는 경우 (목차의 [물어보기]는 입력 중인 글을 건드리지 않는다)
  async function send(question: string, fromInput: boolean) {
    await lock.run(async () => {
      const history = buildHistory(turns); // 성공한 질문과 출처 ID 만
      const key = ++seq.current;
      setError("");
      setTurns((t) => [...t, { key, question, reply: null }]); // "보내는 중…" 으로 보인다
      setTocOpen(false);
      try {
        const reply = await api<Answer>("/chat/guide", { method: "POST", body: { question, history } });
        setTurns((t) => t.map((x) => (x.key === key ? { ...x, reply } : x))); // 답을 붙인다
        if (fromInput) setText(""); // 성공하면 입력창을 비운다
      } catch (e) {
        setTurns((t) => t.filter((x) => x.key !== key)); // 실패한 질문은 목록에서 빼고 (서버에도 보내지 않는다)
        if (!fromInput) setText((cur) => cur || question); // 입력창의 글은 그대로 두고, 목차에서 보낸 질문은 비어 있을 때만 돌려놓는다
        const like = e instanceof ApiError ? e : { status: 0, code: "NETWORK_ERROR" };
        setError(errorText(like));
        if (hidesInput(like)) setNoInput(true);
      }
    });
  }

  function submit() {
    if (verdict !== "OK") return; // 빈 글·초과·10개 참
    void send(text.trim(), true);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (shouldSendOnEnter({ key: e.key, shiftKey: e.shiftKey, isComposing: e.nativeEvent.isComposing })) {
      e.preventDefault(); // 줄바꿈 대신 전송
      submit();
    }
  }

  function newChat() {
    setTurns([]); // 목록과 이전 대화를 비운다 (입력 중인 글은 남긴다)
    setError("");
    setTocOpen(true);
  }

  function showToc() {
    setTocOpen(true);
    requestAnimationFrame(() => toc.current?.scrollIntoView({ block: "start" })); // 펼쳐진 뒤 목차로 옮긴다
  }

  const notice = panelNotice({ noInput, error }); // 입력창이 숨겨지면 새 대화를 눌러도 안내 문장은 남는다
  const canAsk = !lock.busy && !noInput && !full; // 목차의 [물어보기] 사용 가능 여부
  const here = turns.length === 0 ? itemsForPath(items, pathname) : []; // 대화가 비어 있을 때만 "이 화면 안내"

  // 목차 한 줄: 제목(링크 또는 "준비 중") + [물어보기]
  const row = (item: GuideItem) => {
    const href = sourceHref(item.path);
    return (
      <li key={item.id} className="chat-toc-row">
        {href ? <Link href={href} onNavigate={onNavigate}>{item.title}</Link> : <span>{item.title} <small>(준비 중)</small></span>}
        <button type="button" className="chat-ask" disabled={!canAsk} onClick={() => void send(askText(item.title), false)}
          aria-label={`${item.title} 물어보기`}>물어보기</button>
      </li>
    );
  };

  return (
    <section id="chat-panel" className="chat-panel no-print" aria-label="사용법 안내" hidden={!open}
      onKeyDown={(e) => { if (shouldCloseOnKey({ key: e.key, isComposing: e.nativeEvent.isComposing })) onClose(); }}>
      {/* ESC: 키 이벤트는 포커스가 패널 안에 있을 때만 여기로 온다 */}
      <div className="chat-head">
        <strong>사용법 안내</strong>
        <button type="button" disabled={turns.length === 0 || lock.busy} onClick={newChat}>새 대화</button>
        <button type="button" ref={closeRef} className="chat-close" aria-label="사용법 안내 닫기" onClick={onClose}>
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
        </button>
      </div>
      <div className="chat-body" ref={body}>
        {here.length > 0 && (
          <section className="chat-here" aria-label="이 화면 안내">
            <h2>이 화면 안내</h2>
            <ul>{here.map(row)}</ul>
          </section>
        )}
        <div className="chat-log" role="log" aria-live="polite" aria-label="대화">
          {turns.map((t) => (
            <div key={t.key} className="chat-turn">
              <p className="chat-q">{t.question}{t.reply === null && <small> 보내는 중…</small>}</p>
              {t.reply && (
                <div className="chat-a">
                  <p className="chat-text">{t.reply.answer}</p>
                  {t.reply.kind === "NOT_FOUND" && <button type="button" onClick={showToc}>목차 보기</button>}
                  {t.reply.sources.map((s) => {
                    const href = sourceHref(s.path); // 링크는 서버가 준 경로만, 사이트 안 경로일 때만
                    return (
                      <div key={s.id} className="chat-source">
                        <span>{s.title}</span>
                        {href ? <Link href={href} onNavigate={onNavigate}>화면으로 이동</Link> : <small>준비 중</small>}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
        </div>
        <details className="chat-toc" ref={toc} open={tocOpen} onToggle={(e) => setTocOpen(e.currentTarget.open)}>
          <summary>목차</summary>
          <ul>{items.map(row)}</ul>
        </details>
      </div>
      <div className="chat-foot">
        {notice && <p role="alert" className="chat-error">{notice}</p>}
        {full ? (
          <div className="chat-full">
            <p>대화가 길어졌어요. 새 대화를 시작해 주세요</p>
            <button type="button" onClick={newChat}>새 대화</button>
          </div>
        ) : !noInput && (
          <form onSubmit={(e) => { e.preventDefault(); submit(); }}>
            <textarea ref={input} rows={2} maxLength={MAX_QUESTION} value={text} readOnly={lock.busy} aria-label="질문"
              placeholder="사용법을 물어보세요 (Enter 전송, Shift+Enter 줄바꿈)"
              onChange={(e) => setText(e.target.value)} onKeyDown={onKeyDown} />
            <div className="chat-send-row">
              <small>{text.length}/{MAX_QUESTION}</small>
              <button type="submit" disabled={verdict !== "OK" || lock.busy}>{lock.busy ? "보내는 중…" : "보내기"}</button>
            </div>
          </form>
        )}
      </div>
    </section>
  );
}
