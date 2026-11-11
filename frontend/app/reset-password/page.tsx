"use client"; // 입력·클릭을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 화면 이동 링크
import { FormEvent, useState } from "react"; // 폼 제출 이벤트, 화면 상태

import { Field } from "../lib/field"; // 라벨이 테두리에 걸리는 입력 항목
import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { S } from "../lib/styles"; // 화면 공통 스타일

// 메일 링크로 들어와 새 비밀번호를 정하는 화면 (주소 /reset-password?token=...)
export default function ResetPasswordPage() {
  const [next, setNext] = useState(""); // 새 비밀번호
  const [again, setAgain] = useState(""); // 새 비밀번호 확인 (오타 방지)
  const [error, setError] = useState(""); // 오류 문장
  const [done, setDone] = useState(false); // 변경이 끝났는지
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다

  async function onSubmit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    setError("");
    if (next !== again) { // 두 입력이 다르면 서버에 보내지 않는다
      setError("새 비밀번호가 서로 일치하지 않습니다.");
      return;
    }
    const token = new URLSearchParams(window.location.search).get("token") ?? ""; // 메일 링크의 토큰 (제출할 때 읽는다)
    setBusy(true);
    try {
      await api("/auth/password-reset/confirm", { method: "POST", body: { token, new_password: next }, redirectOn401: false });
      setDone(true); // 성공: 로그인 링크를 보여 준다
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "비밀번호를 바꾸지 못했습니다."); // 만료·사용됨·8자 미만 등 서버 문장
    }
    setBusy(false);
  }

  return (
    <main className="login-shell">
      <section className="login-card-pane">
        <div style={S.loginCard}>
          <h1>새 비밀번호 정하기</h1>
          {done ? (
            <p role="status" style={{ marginTop: "var(--space-lg)" }}>비밀번호를 바꿨습니다. <Link href="/login">로그인하기</Link></p>
          ) : (
            <form className="field-form field-stack" onSubmit={onSubmit} style={S.formStack}>
              {error && <p role="alert" style={S.loginAlert}>{error} {error.includes("링크") && <Link href="/forgot-password">다시 요청하기</Link>}</p>}
              {/* 링크가 만료된 경우에는 다시 요청하는 링크를 함께 보여 준다 */}
              <Field label="새 비밀번호 (8자 이상)"><input type="password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} autoFocus autoComplete="new-password" style={S.blockFull} />
              </Field>
              <Field label="새 비밀번호 확인"><input type="password" value={again} onChange={(e) => setAgain(e.target.value)} required autoComplete="new-password" style={S.blockFull} />
              </Field>
              <button type="submit" disabled={busy} style={S.loginSubmit}>{busy ? "변경 중…" : "비밀번호 변경"}</button>
            </form>
          )}
        </div>
      </section>
    </main>
  );
}
