import assert from "node:assert/strict"; // 값 비교
import test from "node:test"; // node --test 방식

import { createSubmitLock } from "./submit-lock.ts"; // 확장자 .ts 포함

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms)); // 요청이 걸리는 시간 흉내

test("동시에 두 번 run 하면 fn 은 한 번만 실행된다", async () => {
  const lock = createSubmitLock();
  let calls = 0;
  const fn = async () => { calls += 1; await wait(10); return "ok"; };
  const [a, b] = await Promise.all([lock.run(fn), lock.run(fn)]);
  assert.equal(calls, 1);
  assert.equal(a, "ok");
  assert.equal(b, undefined); // 무시된 호출은 undefined
});

test("끝난 뒤에는 다시 실행할 수 있다", async () => {
  const lock = createSubmitLock();
  let calls = 0;
  await lock.run(async () => { calls += 1; });
  await lock.run(async () => { calls += 1; });
  assert.equal(calls, 2);
});

test("fn 이 예외를 내도 잠금이 풀리고 예외는 호출한 쪽에 전달된다", async () => {
  const lock = createSubmitLock();
  await assert.rejects(lock.run(async () => { throw new Error("실패"); }), /실패/);
  assert.equal(await lock.run(async () => 7), 7);
});

test("onChange 는 시작 때 true, 끝날 때 false 로 불린다", async () => {
  const seen: boolean[] = [];
  const lock = createSubmitLock((b) => seen.push(b));
  await lock.run(async () => 1);
  assert.deepEqual(seen, [true, false]);
});
