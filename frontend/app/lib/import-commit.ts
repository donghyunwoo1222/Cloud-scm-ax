// 판매·입고 가져오기 반영(commit)이 409 PREVIEW_CHANGED 로 거절됐는지 판단하는 순수 로직 (#258)

export const PREVIEW_CHANGED_NOTICE = "미리보기 이후 데이터가 바뀌었어요. 미리보기를 다시 눌러 주세요"; // 화면에 보일 안내

/** 서버 오류(ApiError 모양)가 "미리보기와 달라짐"이면 true. 예) { status: 409, code: "PREVIEW_CHANGED" } */
export function isPreviewChanged(e: unknown): boolean {
  const x = e as { status?: unknown; code?: unknown } | null;
  return !!x && x.status === 409 && x.code === "PREVIEW_CHANGED";
}
