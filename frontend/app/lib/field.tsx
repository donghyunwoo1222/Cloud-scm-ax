import type { ReactNode } from "react"; // 라벨과 입력칸 타입

// 입력 항목 하나: 라벨 글자(span)와 입력칸(children)을 <label> 로 감싼다.
// 데스크톱(730px 이상)에서는 지금처럼 라벨이 입력칸 위에 있고, 모바일에서는 globals.css 가 라벨을 입력칸 위쪽 테두리에 걸쳐 보여 준다.
// short 를 주면 모바일처럼 좁은 폭에서만 짧은 라벨을 보인다(예: "재고 단위 단가(원)*" → "단가(원)*").
export function Field({ label, short, className = "", children }: {
  label: ReactNode; // 라벨 글자 (필수 표시 * 도 여기에 넣는다)
  short?: string; // 모바일에서 대신 보일 짧은 라벨
  className?: string; // 폭 규칙 (예: field-half = 모바일에서 두 칸씩)
  children: ReactNode; // 입력칸 (input, select 등)
}) {
  return (
    <label className={`field ${className}`.trim()}>
      <span className="field-label">
        {short ? (
          <>
            <span className="lb-full">{label}</span>
            <span className="lb-short">{short}</span>
          </>
        ) : label}
      </span>
      {children}
    </label>
  );
}
