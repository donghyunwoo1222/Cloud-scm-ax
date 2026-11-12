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
  body?: unknown; // 보낼 JSON 본문 (FormData 면 파일 업로드: 그대로 보낸다)
  redirectOn401?: boolean; // 401 이면 로그인 화면으로 보낼지 (로그인 요청 자체는 false)
  headers?: Record<string, string>; // 더 붙일 헤더 (예: Idempotency-Key, #190)
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

const MAX_PAGES = 100; // 안전장치: 한 번의 apiListAll 이 읽는 쪽 수 (100쪽 × 100개 = 1만 개)

// 목록을 100개씩 끝까지 읽어 한 배열로 돌려준다 (서버의 쪽 크기 상한 100은 그대로 두고, 어떤 항목이든 끝까지 닿게 한다, #184)
// 예) 업체 250곳 → 요청 3번(100 + 100 + 50). path 에 이미 ?조건이 있어도 된다 (예: "/suppliers?include_inactive=true")
// 멈추는 때: ① 빈 쪽이 오면 ② 읽은 개수가 "방금 받은" meta.total 이상이면(읽는 도중 total 이 줄거나 늘어도 그 값을 따른다)
// ③ 100쪽을 넘기면 무한 반복을 막으려고 오류를 던진다
export async function apiListAll<T>(path: string): Promise<T[]> {
  const rows: T[] = []; // 지금까지 읽은 행
  const sep = path.includes("?") ? "&" : "?"; // 조건이 이미 있으면 & 로 잇는다
  for (let page = 1; page <= MAX_PAGES; page++) { // 최대 100쪽
    const result = await apiList<T>(`${path}${sep}page_size=100&page=${page}`); // 한 쪽
    rows.push(...result.data); // 뒤에 붙인다
    if (result.data.length === 0 || rows.length >= result.meta.total) return rows; // 빈 쪽이거나 total 만큼 읽었으면 끝
  }
  throw new Error(`목록이 너무 많아 ${MAX_PAGES}쪽까지 읽고 멈췄습니다. 검색 조건을 좁혀 주세요.`); // 100쪽 넘으면 오류
}

// 요청을 보내고 성공 본문(JSON)을 돌려주거나 ApiError 를 던지는 공통 부분
async function request(path: string, options: Options) {
  const { method = "GET", body, redirectOn401 = true, headers: extra } = options; // 기본값: GET, 401 이면 이동
  let response: Response; // 서버 응답
  try {
    response = await fetch(`/api/v1${path}`, {
      method, // 요청 방식
      // FormData 는 브라우저가 경계 문자열이 든 Content-Type 을 직접 붙이므로 우리가 지정하지 않는다
      headers: body === undefined || body instanceof FormData ? extra : { "Content-Type": "application/json", ...extra }, // 본문이 JSON 일 때만 표시 + 더 붙일 헤더
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body), // 객체 → JSON 문자열
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
