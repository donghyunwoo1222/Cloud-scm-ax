// 품목 옵션(색상·사이즈·규격)을 한 줄로 요약하는 공통 함수. 요약 문자열은 이 파일에서만 만든다 (#178)

export type Options = { color?: string | null; size?: string | null; spec?: string | null }; // 서버가 내려주는 옵션 칸 (없으면 null)

// 이력 응답은 칸 이름이 product_color 처럼 다르다 → 같은 모양으로 바꿔 쓴다
export type MovementOptions = { product_color?: string | null; product_size?: string | null; product_spec?: string | null };

export function movementOptions(m: MovementOptions): Options {
  return { color: m.product_color, size: m.product_size, spec: m.product_spec };
}

// 예) {color:"검정", size:"M"} → "검정 / M", 옵션이 없으면 "" (화면에 아무것도 그리지 않는다)
export function optionSummary(o: Options): string {
  return [o.color, o.size, o.spec].filter((v): v is string => Boolean(v)).join(" / ");
}

// 예) ("TS-BK-M", {color:"검정", size:"M"}) → "TS-BK-M · 검정 / M", 옵션이 없으면 "TS-BK-M" 그대로
export function skuWithOptions(sku: string | null, o: Options): string {
  const summary = optionSummary(o);
  return summary ? `${sku ?? ""} · ${summary}` : (sku ?? "");
}
