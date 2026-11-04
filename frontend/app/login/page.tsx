"use client"; // 입력·클릭을 다루는 화면이라 브라우저에서 실행

import { useRouter } from "next/navigation"; // 화면 이동 도구
import { FormEvent, useEffect, useState } from "react"; // 폼 제출 이벤트, 처음 한 번 실행, 화면 상태

import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { S } from "../lib/styles"; // 화면 공통 스타일

// 로그인 화면 (주소 /login)
export default function LoginPage() {
  const router = useRouter(); // 로그인 성공 후 이동에 쓴다
  const [email, setEmail] = useState(""); // 입력한 이메일
  const [password, setPassword] = useState(""); // 입력한 비밀번호
  const [error, setError] = useState(""); // 화면에 보일 오류 문장
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다 (두 번 누르기 방지)

  useEffect(() => {
    // 이미 로그인한 상태로 /login 을 열면 대시보드로 보낸다 (로그인 안 했으면 401 이지만 여기서는 이동하지 않고 그대로 둔다)
    api("/me", { redirectOn401: false }).then(() => router.replace("/dashboard")).catch(() => {});
  }, [router]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault(); // 브라우저 기본 동작(페이지 새로고침)을 막는다
    setBusy(true); // 버튼 잠금
    setError(""); // 이전 오류 지우기
    try {
      // 서버가 토큰을 httpOnly 쿠키로 내려준다. 화면 코드는 토큰을 직접 다루지 않는다
      await api("/auth/login", { method: "POST", body: { email, password }, redirectOn401: false });
      setPassword(""); // 로그아웃 뒤 다시 열린 로그인 화면(Next.js 가 상태를 그대로 보관한다)에 이전 비밀번호가 남지 않게 비운다
      setBusy(false); // 같은 이유로 버튼 잠금도 풀어 둔다 (안 풀면 로그아웃 후 "로그인 중…" 으로 멈춘다)
      router.replace("/dashboard"); // 성공: 대시보드로 (뒤로 가기로 로그인 화면에 돌아오지 않게 replace)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "로그인하지 못했습니다."); // 서버가 준 문장을 그대로 보여준다
      setBusy(false); // 다시 시도할 수 있게 잠금 해제
    }
  }

  return (
    <main style={S.loginPage}>
      {/* 화면 여백과 폭 */}
      <h1>Cloud SCM + AX 로그인</h1>
      <form onSubmit={onSubmit} style={S.formStack}>
        {/* 입력칸을 세로로 쌓는다 */}
        <label>
          이메일
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="username" style={S.blockFull} />
        </label>
        <label>
          비밀번호
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" style={S.blockFull} />
        </label>
        {error && <p role="alert" style={S.error}>{error}</p>}
        {/* 오류가 있을 때만 표시. role="alert" 는 화면 낭독기가 바로 읽게 한다 */}
        <button type="submit" disabled={busy}>
          {busy ? "로그인 중…" : "로그인"}
        </button>
      </form>
    </main>
  );
}
