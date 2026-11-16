// 로그인 뒤 돌아갈 주소(next)를 검사한다. 통과하면 그 경로를, 하나라도 걸리면 항상 "/dashboard"를 돌려준다.
// 규칙: docs/06-system-design/channels-and-deeplinks.md 의 C-(1)~(8).
// ⚠ 허용 경로 14개는 서버가 알림 링크를 만드는 쪽과 같아야 한다. 서버(backend/app/services/slack_digest.py 의 WEB_PATH,
//   slack_events.py 의 WEB_ORDERS_PATH)에는 허용 목록 상수가 없고 경로 둘이 따로 적혀 있다. 화면을 더하면 문서 표와 여기를 함께 고친다.

const FALLBACK = "/dashboard"; // 실패하면 가는 곳
const MAX_LENGTH = 200; // 허용 경로는 훨씬 짧다. 너무 긴 값은 디코딩 전에 버린다

// 허용 경로 14개 (문서 표 순서). {id}는 숫자만
const ALLOWED = [
  /^\/dashboard$/,
  /^\/inventory$/,
  /^\/recommendations$/,
  /^\/purchase-orders$/,
  /^\/purchase-orders\/\d+$/,
  /^\/purchase-orders\/\d+\/document$/,
  /^\/receipts$/,
  /^\/shipments$/,
  /^\/products$/,
  /^\/suppliers$/,
  /^\/suppliers\/\d+$/,
  /^\/company$/,
  /^\/slack$/,
  /^\/users$/,
];

// raw: 주소창의 next 값 그대로(아직 디코딩 안 한 것). 디코딩은 이 함수 안에서 정확히 한 번만 한다
export function safeNext(raw: unknown): string {
  // 문자열이 아니거나 너무 길면 거절 (예: undefined, 1000자 문자열)
  if (typeof raw !== "string" || raw.length > MAX_LENGTH) return FALLBACK;

  // 딱 한 번만 디코딩. 깨진 인코딩은 거절 (예: %E0%A4%A). 두 번 풀면 %252F 가 검사 뒤에 // 로 바뀔 수 있다
  let path: string;
  try {
    path = decodeURIComponent(raw);
  } catch {
    return FALLBACK;
  }

  // 공백·제어문자 거절 (예: "/dashboard\n", 줄바꿈으로 헤더·주소를 속이는 값)
  if (/[\s\u0000-\u001f\u007f-\u009f]/.test(path)) return FALLBACK;
  // /로 시작하지 않으면 거절 (예: https://evil.com, javascript:alert(1))
  if (!path.startsWith("/")) return FALLBACK;
  // 백슬래시 거절: 브라우저가 \ 를 / 로 읽는다 (예: /\evil.com → //evil.com). %5C 도 위에서 디코딩되어 여기서 걸린다 (C-8)
  if (path.includes("\\")) return FALLBACK;
  // .. 거절 (예: /purchase-orders/../users)
  if (path.includes("..")) return FALLBACK;
  // 첫 글자 뒤에 // 가 있으면 거절. slice(1)이라 시작하는 // 도 걸린다 (예: //evil.com 은 다른 사이트 주소)
  if (path.slice(1).includes("//")) return FALLBACK;
  // 쿼리(?)·해시(#)가 붙으면 거절 (예: /products?x=1). 허용 경로는 쿼리 없이 경로만 쓴다
  if (path.includes("?") || path.includes("#")) return FALLBACK;
  // 허용 경로 14개 중 하나여야 통과 (예: /login, /products/new, /purchase-orders/abc 는 거절)
  if (!ALLOWED.some((re) => re.test(path))) return FALLBACK;

  return path;
}
