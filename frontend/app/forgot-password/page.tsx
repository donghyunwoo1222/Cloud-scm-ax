"use client"; // 입력·클릭을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 로그인 화면으로 돌아가는 링크
import { FormEvent, useState } from "react"; // 폼 제출 이벤트, 화면 상태

import { Field } from "../lib/field"; // 라벨이 테두리에 걸리는 입력 항목
import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { S } from "../lib/styles"; // 화면 공통 스타일

// 비밀번호 재설정 메일 요청 화면 (주소 /forgot-password)
export default function ForgotPasswordPage() {
  const [email, setEmail] = useState(""); // 입력한 이메일
  const [done, setDone] = useState(""); // 서버가 준 안내 문장 (있든 없든 같은 문장)
  const [error, setError] = useState(""); // 오류 문장 (429·503 등)
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다

  async function onSubmit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    setBusy(true);
    setError("");
    try {
      const res = await api<{ message: string }>("/auth/password-reset/request", { method: "POST", body: { email }, redirectOn401: false });
      setDone(res.message); // 가입 여부와 상관없이 같은 문장
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "요청하지 못했습니다."); // 서버 문장 그대로
    }
    setBusy(false);
  }

  return (
    <main className="login-shell">
      <section className="login-card-pane">
        <div style={S.loginCard}>
          <h1>비밀번호 재설정</h1>
          <p style={S.hint}>가입한 이메일을 입력하면 재설정 링크를 보내 드립니다. 링크는 30분 동안, 한 번만 쓸 수 있습니다.</p>
          {done ? (
            <p role="status" style={{ marginTop: "var(--space-lg)" }}>{done}</p>
          ) : (
            <form className="field-form field-stack" onSubmit={onSubmit} style={S.formStack}>
              {error && <p role="alert" style={S.loginAlert}>{error}</p>}
              {/* 오류가 있을 때만 표시 */}
              <Field label="이메일"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="username" style={S.blockFull} />
              </Field>
              <button type="submit" disabled={busy} style={S.loginSubmit}>{busy ? "보내는 중…" : "재설정 메일 보내기"}</button>
            </form>
          )}
          <p style={{ ...S.hint, marginTop: "var(--space-md)" }}><Link href="/login">로그인으로 돌아가기</Link></p>
        </div>
      </section>
    </main>
  );
}
