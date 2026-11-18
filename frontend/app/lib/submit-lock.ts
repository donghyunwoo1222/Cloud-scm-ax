import { useMemo, useState } from "react"; // 잠금은 한 번만 만들고, 화면 표시용 상태를 둔다

// 중복 클릭 잠금: run(fn) 이 실행 중일 때 들어온 run 은 fn 을 부르지 않고 undefined 를 돌려준다.
// 끝나면(성공·실패 모두) 잠금이 풀린다. 상태값은 늦게 바뀌므로 잠금 자체는 일반 변수로 즉시 건다.
export function createSubmitLock(onChange?: (busy: boolean) => void) {
  let locked = false; // 실행 중 표시
  return {
    async run<T>(fn: () => Promise<T>): Promise<T | undefined> {
      if (locked) return undefined; // 이미 실행 중: 무시
      locked = true;
      onChange?.(true);
      try {
        return await fn(); // 반환값은 호출한 쪽으로 그대로 전달
      } finally {
        locked = false; // 예외가 나도 푼다
        onChange?.(false);
      }
    },
  };
}

// 화면용 훅: run 으로 감싸고, busy 는 버튼 비활성·표시 문구에 쓴다 (요청은 직접 보내지 않는다)
export function useSubmitLock() {
  const [busy, setBusy] = useState(false);
  const lock = useMemo(() => createSubmitLock(setBusy), []);
  return { run: lock.run, busy };
}
