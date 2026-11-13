"use client"; // 상태·타이머·클릭을 쓰는 부품이라 브라우저에서 실행

import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react"; // 공유 상자, 함수 고정, 상태, 타이머 보관용 ref

const MAX_TOASTS = 3; // 동시에 쌓이는 최대 개수: 넘으면 가장 오래된 것부터 지운다
const SHOW_MS = 6000; // 자동으로 사라지기까지 6초

type Toast = { id: number; text: string };

// 화면에서는 const toast = useToast(); toast("품목을 수정했어요") 처럼 부른다. provider 밖에서 불러도 아무 일 없이 지나간다
const ToastContext = createContext<(text: string) => void>(() => {});
export const useToast = () => useContext(ToastContext);

// 성공 알림 토스트: (app) 레이아웃에 한 번만 두면 화면을 옮겨도 유지된다(레이아웃은 이동 때 다시 그려지지 않는다).
// 실패는 토스트로 알리지 않고 화면의 오류 문구로 남긴다
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]); // 화면에 떠 있는 알림 (오래된 것이 앞)
  const current = useRef<Toast[]>([]); // 같은 값을 동기로 읽으려는 사본 (같은 문구 합치기, 개수 제한에 쓴다)
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>()); // 알림마다 하나씩 건 사라짐 타이머
  const nextId = useRef(0); // 알림 번호

  const commit = useCallback((next: Toast[]) => { current.current = next; setToasts(next); }, []);

  const dismiss = useCallback((id: number) => {
    clearTimeout(timers.current.get(id)); // 닫기 버튼으로 닫았으면 타이머도 끈다
    timers.current.delete(id);
    commit(current.current.filter((t) => t.id !== id));
  }, [commit]);

  const toast = useCallback((text: string) => {
    const same = current.current.find((t) => t.text === text);
    if (same) dismiss(same.id); // 같은 문구가 또 오면 쌓지 않고 새로 띄워 타이머를 다시 시작한다
    const id = ++nextId.current;
    let next = [...current.current, { id, text }];
    while (next.length > MAX_TOASTS) { // 넘치는 가장 오래된 알림은 타이머까지 함께 지운다
      clearTimeout(timers.current.get(next[0].id));
      timers.current.delete(next[0].id);
      next = next.slice(1);
    }
    commit(next);
    timers.current.set(id, setTimeout(() => dismiss(id), SHOW_MS));
  }, [commit, dismiss]);

  useEffect(() => {
    const all = timers.current;
    return () => all.forEach(clearTimeout); // 레이아웃이 사라질 때 남은 타이머 정리
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {/* 영역은 처음부터 DOM 에 있어야 스크린리더가 안에 추가되는 알림을 읽는다 (role="status" = aria-live polite) */}
      <div className="toast-region no-print" role="status">
        {toasts.map((t) => (
          <div key={t.id} className="toast">
            <span>{t.text}</span>
            <button type="button" aria-label="알림 닫기" onClick={() => dismiss(t.id)}><span aria-hidden="true">×</span></button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
