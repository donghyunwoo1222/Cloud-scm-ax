// 모든 화면이 쓰는 API 호출 함수 하나.
// - 주소는 항상 /api/v1/... 상대 경로: 브라우저는 Next.js 주소로만 요청하고, Next.js 가 백엔드로 전달한다(rewrites).
// - 성공이면 응답의 data 를(목록은 apiList 로 data·meta 를), 실패면 서버의 error.code·message 를 담은 ApiError 를 던진다.
// - 401(로그인 필요)이면 로그인 화면으로 보낸다.

// 서버가 돌려준 오류 한 건 (서버 형식: {"error": {"code", "message", "details"}})
export class ApiError extends Error {
  constructor(
    public status: number, // HTTP 상태 코드 (예: 401, 409)
    public code: string, // 화면이 분기할 영문 코드 (예: DUPLICATE_SKU)
    message: string, // 화면에 그대로 보여줄 한국어 문장
    public details: unknown = null, // 어느 칸이 문제인지 등 (없으면 null)
  ) {
    super(message); // Error 의 message 로 저장
  }
}

type Options = {
  method?: "GET" | "POST" | "PATCH"; // 상태를 바꾸는 요청은 POST/PATCH 만 쓴다 (GET 은 읽기만)
  body?: unknown; // 보낼 JSON 본문
  redirectOn401?: boolean; // 401 이면 로그인 화면으로 보낼지 (로그인 요청 자체는 false)
};

// 목록 응답의 쪽 정보 (서버 meta)
export type Meta = { page: number; page_size: number; total: number };

// 한 건·동작 요청: 성공하면 data 만 돌려준다
export async function api<T>(path: string, options: Options = {}): Promise<T> {
  const json = await request(path, options); // 공통 처리
  return (json?.data ?? null) as T; // data 만 꺼내 준다 (204 면 null)
}

// 목록 요청: data(배열)와 meta(쪽 정보)를 함께 돌려준다
export async function apiList<T>(path: string): Promise<{ data: T[]; meta: Meta }> {
  const json = await request(path, {}); // 공통 처리 (GET)
  return { data: json.data, meta: json.meta }; // 목록 모양 그대로
}

// 요청을 보내고 성공 본문(JSON)을 돌려주거나 ApiError 를 던지는 공통 부분
async function request(path: string, options: Options) {
  const { method = "GET", body, redirectOn401 = true } = options; // 기본값: GET, 401 이면 이동
  let response: Response; // 서버 응답
  try {
    response = await fetch(`/api/v1${path}`, {
      method, // 요청 방식
      headers: body === undefined ? undefined : { "Content-Type": "application/json" }, // 본문이 있을 때만 JSON 표시
      body: body === undefined ? undefined : JSON.stringify(body), // 객체 → JSON 문자열
      credentials: "same-origin", // 같은 주소의 쿠키(로그인 토큰)를 자동으로 붙인다
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "서버에 연결할 수 없습니다."); // 서버가 꺼졌거나 네트워크 끊김
  }

  if (response.status === 204) return null; // 본문 없는 성공 (예: 로그아웃)

  const json = await response.json().catch(() => null); // JSON 이 아니면 null (예: 백엔드가 꺼져 프록시 오류 화면이 온 경우)

  if (response.ok && json) return json; // 성공: 본문 전체 ({"data": ..., "meta": ...})

  if (response.status === 401 && redirectOn401) {
    // 이 함수는 React 컴포넌트 밖이라 useRouter 를 쓸 수 없고, 전체 새로고침으로 이전 사용자의 화면 상태도 비우려고 일부러 쓴다
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign("/login"); // 로그인이 풀렸으면 로그인 화면으로
  }
  const error = json?.error; // 서버 오류 본문
  throw new ApiError(
    response.status,
    error?.code ?? "UNKNOWN_ERROR", // 서버가 코드를 안 줬으면 공통 코드
    error?.message ?? "요청을 처리하지 못했습니다.", // 서버 문장이 없으면 공통 문장
    error?.details ?? null,
  );
}
