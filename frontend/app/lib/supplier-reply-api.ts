// 공급업체 확인 화면 전용 호출(#265). 공용 api() 를 쓰지 않는 이유:
// 401 이면 로그인 화면으로 보내는 처리가 있고 로그인 쿠키를 붙이기 때문이다(공개 화면에서는 둘 다 틀린다).
// 그래서 쿠키를 보내지 않고(omit) 이동도 하지 않는다. 토큰은 POST 본문으로만 보낸다.
import { ApiError } from "./api"; // 오류 클래스만 재사용
import type { ReplyView } from "./supplier-reply";

async function post(path: string, body: unknown): Promise<ReplyView> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/supplier-reply/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      credentials: "omit", // 담당자 로그인 쿠키가 공급업체 경로로 가지 않게
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다.");
  }
  const json = await response.json().catch(() => null);
  if (response.ok && json?.data) return json.data as ReplyView;
  const error = json?.error;
  throw new ApiError(response.status, error?.code ?? "UNKNOWN_ERROR", error?.message ?? "요청을 처리하지 못했습니다.", error?.details ?? null);
}

export const viewReply = (token: string) => post("view", { token });
export const confirmReply = (token: string, due_date?: string) => post("confirm", due_date ? { token, due_date } : { token });
