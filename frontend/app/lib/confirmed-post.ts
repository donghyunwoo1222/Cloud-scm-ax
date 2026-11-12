// 입출고·정정·발주 입고 POST 공통 (#190): 멱등 키를 붙이고, 409 CONFIRM_REQUIRED 면 확인창을 띄운 뒤 같은 키로 다시 보낸다.
// 키 수명: 보낼 본문이 직전에 보낸 본문과 같으면 같은 키(확인 뒤 재전송·네트워크 오류 재시도), 다르면 새 키, 성공하면 버린다.
// 서버는 같은 키 + 다른 내용을 422 로 막으므로, "입력이 바뀌면 새 키"를 칸마다 챙기지 않고 본문 비교 하나로 지킨다.
"use client";

import { useRef } from "react"; // 화면이 다시 그려져도 남는 키 보관

import { api, ApiError } from "./api"; // 공통 API 호출, 서버 오류

type Warning = { code: string; product_id: number; quantity?: number; sales_30d?: number; limit?: number }; // 서버 details.warnings 한 건

// 키 순서를 고정한 JSON 글자: {a:1,b:2} 와 {b:2,a:1} 을 같은 본문으로 본다
export function stableJson(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value).filter(([, v]) => v !== undefined).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)); // undefined 칸은 JSON 에도 안 나간다
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableJson(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

// 경고 목록 → 확인창 문장. names 는 화면이 이미 가진 {품목 번호: 이름}, 없으면 "품목 #번호"
function confirmText(error: ApiError, names: Record<number, string>): string {
  const warnings = ((error.details as { warnings?: Warning[] } | null)?.warnings ?? []);
  const nameOf = (id: number) => names[id] ?? `품목 #${id}`;
  const n = (x?: number) => (x ?? 0).toLocaleString("ko-KR"); // 예: 1,900
  const lines = warnings.map((w) => {
    if (w.code === "LARGE_QUANTITY") return `${nameOf(w.product_id)}의 입력 수량 ${n(w.quantity)}이(가) 최근 30일 판매량 ${n(w.sales_30d)}의 3배(${n(w.limit)})를 넘습니다. 그대로 저장할까요?`;
    if (w.code === "INACTIVE_PRODUCT") return `${nameOf(w.product_id)}은(는) 비활성 품목입니다. 그대로 진행할까요?`;
    return null; // 모르는 코드
  });
  const known = lines.filter((l): l is string => l !== null);
  return known.length === lines.length && known.length > 0 ? known.join("\n") : [...known, error.message].join("\n"); // 모르는 코드가 있으면 서버 문장을 그대로
}

// 사용법: const post = useConfirmedPost(); const r = await post<T>(경로, 본문, {품목 번호: 이름}); r 이 null 이면 사용자가 확인창을 취소한 것
export function useConfirmedPost() {
  const last = useRef<{ body: string; key: string } | null>(null); // 직전에 보낸 본문(confirm_warnings 제외)과 그 키

  return async function post<T>(path: string, body: Record<string, unknown>, names: Record<number, string> = {}): Promise<T | null> {
    const signature = `${path} ${stableJson(body)}`; // 경로까지 같아야 같은 요청
    if (last.current?.body !== signature) last.current = { body: signature, key: crypto.randomUUID() }; // 내용이 바뀌었으면 새 키
    const headers = { "Idempotency-Key": last.current.key };
    let result: T;
    try {
      result = await api<T>(path, { method: "POST", body, headers });
    } catch (e) {
      if (!(e instanceof ApiError && e.code === "CONFIRM_REQUIRED")) throw e; // 그 밖의 오류는 키를 남겨 둔다 (같은 내용 재시도 = 같은 키)
      if (!window.confirm(confirmText(e, names))) return null; // 취소: 아무것도 보내지 않는다 (입력 유지)
      result = await api<T>(path, { method: "POST", body: { ...body, confirm_warnings: true }, headers }); // 같은 키로 확인 후 재전송
    }
    last.current = null; // 성공: 다음 제출은 새 키
    return result;
  };
}
