"use client"; // 확인 화면의 버튼이 브라우저에서 동작한다

import { api } from "./api"; // 서버 호출
import { S } from "./styles"; // 공통 스타일

// 가져오기 3종(판매·품목·입고)이 함께 쓰는 "이렇게 읽었어요" 부품 (#193).
// 상태(reading·reqId 등)와 분기는 각 화면이 가진다. 여기에는 타입·호출·확인 표만 둔다.

// /suggest 응답. K 는 그 가져오기의 칸 이름들(예: "product_col"). rules 면 mapping·confidence·samples 가 null, reason 은 코드 값(화면에 그대로 보이지 않는다)
export type Suggest<K extends string> = {
  source: "template" | "llm" | "rules"; reason: string | null; mapping: Record<K, number | null> | null;
  confidence: Partial<Record<K, "high" | "low">> | null; samples: Partial<Record<K, string[]>> | null;
};

export const NO_AI_REASONS = ["DAILY_LIMIT", "BUDGET"]; // 한도 초과일 때만 "AI 추천을 쓸 수 없어요" 안내 (꺼짐·장애는 조용히 기존 화면)
export const NO_AI_NOTICE = "오늘은 AI 추천을 쓸 수 없어 기본 추천으로 열었어요.";

// 파일로 /suggest 를 한 번 부른다. 어떤 오류든 삼키고 null (값은 로그·오류에 남기지 않는다) → 화면은 기존 열 지정으로 이어간다
export async function fetchSuggest<K extends string>(path: string, file: File): Promise<Suggest<K> | null> {
  const body = new FormData();
  body.append("file", file);
  try { return await api<Suggest<K>>(path, { method: "POST", body }); } catch { return null; }
}

const RED = { color: "var(--color-destructive)" } as const;
const ACTIONS = { display: "flex", flexWrap: "wrap", alignItems: "flex-end", gap: "var(--space-sm) var(--space-md)", marginTop: "var(--space-lg)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--color-border)" } as const;

// "이렇게 읽었어요. 맞나요?" 카드: 파일 열 → 읽은 칸 → 값 예시. 확신 낮은 칸은 글자로도 강조한다.
// required: 이 칸 중 하나라도 짝이 없으면 "맞아요"를 막는다. show: 짝이 없어도 행을 보여 줄 칸(필수·경고). 그 밖의 칸은 짝이 있을 때만 보인다.
// warn: 짝이 없을 때 그 행에 붙일 문구(기본 "읽지 못함"). note: 표 아래 한 줄 설명.
export function ReadingConfirm<K extends string>({ fields, mapping, samples, confidence, header, required, show, warn, note, busy, onYes, onNo }: {
  fields: readonly (readonly [K, string])[]; mapping: Record<K, number | null>; samples: Partial<Record<K, string[]>>;
  confidence: Partial<Record<K, "high" | "low">>; header: (col: number) => string; required: K[]; show: K[];
  warn?: Partial<Record<K, string>>; note?: string; busy: boolean; onYes: () => void; onNo: () => void;
}) {
  return (
    <div style={S.sectionCard}>
      <h2 style={{ marginTop: 0 }}>2. 이렇게 읽었어요. 맞나요?</h2>
      <p style={S.hint}>파일의 열이 어떤 칸으로 읽혔는지와 그 열의 앞쪽 값을 보여줍니다. 값이 이상하면 &quot;다르게 읽혔어요&quot;를 누르세요.</p>
      <div style={S.tableBox}>
        <table style={S.table}>
          <thead><tr style={S.headRow}><th>파일의 열</th><th>읽은 칸</th><th>값 예시</th></tr></thead>
          <tbody>
            {fields.map(([k, label]) => {
              const col = mapping[k] ?? null;
              if (col === null && !show.includes(k)) return null; // 선택 칸은 짝이 없으면 숨긴다
              const low = confidence[k] === "low";
              return (
                <tr key={k} style={S.row}>
                  <td>{col === null ? "-" : header(col)}</td>
                  <td>{label}{col === null && <strong style={RED}> {warn?.[k] ?? "읽지 못함"}</strong>}
                    {low && <strong style={RED}> 확신 낮음</strong>}</td>
                  <td style={low ? { fontWeight: 600 } : undefined}>{(samples[k] ?? []).join(", ") || "-"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {note && <p style={{ ...S.hint, marginBottom: 0 }}>{note}</p>}
      <div style={ACTIONS}>
        <button type="button" className="primary-action" disabled={busy || required.some((k) => mapping[k] === null)} onClick={onYes}>맞아요</button>
        <button type="button" disabled={busy} onClick={onNo}>다르게 읽혔어요</button>
      </div>
    </div>
  );
}
