"use client"; // 끌어 놓기(drag & drop) 상태를 다루는 부품이라 브라우저에서 실행

import { useState } from "react"; // 파일을 끌고 들어온 중인지 기억

// 가져오기 화면(판매·품목·품목·입고) 공통 "1. 파일 올리기" 칸.
// 눌러서 고르기와 끌어 놓기 둘 다 받는다. 실제 input 은 칸 전체를 덮는 label 안에 있어 키보드·화면 낭독기로도 쓸 수 있다
export function FileDrop({ label, disabled, fileName, meta, templates, onFile }: {
  label: string; // 화면 낭독기용 이름 (예: "주문 파일")
  disabled?: boolean; // 요청 중이면 막는다
  fileName?: string; // 고른 파일 이름 (없으면 안내 문구)
  meta?: string; // 파일 이름 아래 보조 정보 (예: "데이터 120행")
  templates?: { xlsx: string; csv: string }; // 템플릿 내려받기 주소 (없으면 줄을 숨긴다)
  onFile: (f: File | null) => void; // 파일을 고르거나 놓으면 부른다
}) {
  const [over, setOver] = useState(false); // 파일을 칸 위로 끌고 온 중인지 (테두리 강조)
  const [wrong, setWrong] = useState(""); // 형식이 맞지 않는 파일을 놓았을 때 안내

  // 끌어 놓기는 input 의 accept 제한을 받지 않으니 확장자를 직접 본다 (최종 검사는 서버가 한다)
  function drop(f: File) {
    if (!/\.(csv|xlsx)$/i.test(f.name)) { setWrong(`${f.name}: csv나 xlsx 파일만 올릴 수 있어요.`); return; }
    setWrong("");
    onFile(f);
  }

  return (
    <div>
      <label className={`file-drop${over ? " is-over" : ""}${fileName ? " has-file" : ""}`} aria-disabled={disabled || undefined}
        onDragOver={(e) => { e.preventDefault(); if (!disabled) setOver(true); }} // 기본 동작(브라우저가 파일을 여는 것)을 막아야 drop 이 온다
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f && !disabled) drop(f); }}>
        {/* span 으로 감싸 globals.css 의 "label > input" 폼 칸 규칙(폭 320px·세로 나열)을 피한다 */}
        <span><input type="file" accept=".csv,.xlsx" disabled={disabled} aria-label={label} className="file-drop-input"
          onChange={(e) => { setWrong(""); onFile(e.target.files?.[0] ?? null); }} /></span>
        <svg aria-hidden="true" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          {fileName
            ? <><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /><path d="m9 14 2 2 4-4" /></> // 파일 + 체크
            : <><path d="M12 15V4" /><path d="m7 9 5-5 5 5" /><path d="M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3" /></>}
        </svg>
        <span className="file-drop-main">{fileName ?? "파일을 끌어 놓거나 눌러서 고르세요"}</span>
        <span className="file-drop-sub">{fileName ? `${meta ? `${meta} · ` : ""}다른 파일로 바꾸려면 다시 누르세요` : ".csv · .xlsx, 5MB · 5,000행 이하"}</span>
      </label>
      {wrong && <p role="alert" style={{ color: "var(--color-destructive)", margin: "var(--space-sm) 0 0" }}>{wrong}</p>}
      {templates && (
        <p className="file-drop-templates">
          <span>양식이 없나요?</span>
          <a href={templates.xlsx} download>엑셀 템플릿</a>
          <a href={templates.csv} download>CSV 템플릿</a>
        </p>
      )}
    </div>
  );
}
