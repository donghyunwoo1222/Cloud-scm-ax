"use client"; // 입력·클릭을 다루는 화면이라 브라우저에서 실행

import { useRouter } from "next/navigation"; // 화면 이동 도구
import { FormEvent, useState } from "react"; // 폼 제출 이벤트, 화면 상태

import { Field } from "../lib/field"; // 라벨이 테두리에 걸리는 입력 항목
import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { S } from "../lib/styles"; // 화면 공통 스타일

// 임시 비밀번호로 로그인한 직원이 처음 오는 비밀번호 변경 화면 (주소 /change-password)
export default function ChangePasswordPage() {
  const router = useRouter(); // 성공 후 이동에 쓴다
  const [current, setCurrent] = useState(""); // 지금(임시) 비밀번호
  const [next, setNext] = useState(""); // 새 비밀번호
  const [again, setAgain] = useState(""); // 새 비밀번호 확인 입력 (오타 방지)
  const [error, setError] = useState(""); // 화면에 보일 오류 문장
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다 (두 번 누르기 방지)

  async function onSubmit(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    setError("");
    if (next !== again) { // 두 입력이 다르면 서버에 보내지 않고 안내한다 (오타로 잠기는 것 방지)
      setError("새 비밀번호가 서로 일치하지 않습니다.");
      return;
    }
    setBusy(true);
    try {
      // 현재 비밀번호가 틀리면 401 이지만 로그인 화면으로 보내지 않고 이 화면에서 문장을 보여 준다
      await api("/auth/password", { method: "POST", body: { current_password: current, new_password: next }, redirectOn401: false });
      router.replace("/dashboard"); // 성공: 표시가 꺼졌으니 대시보드로
    } catch (e) {
      if (e instanceof ApiError && e.code === "UNAUTHENTICATED") {
        router.replace("/login"); // 로그인 자체가 풀렸으면 로그인 화면으로
        return;
      }
      setError(e instanceof ApiError ? e.message : "비밀번호를 바꾸지 못했습니다."); // 서버 문장을 그대로 보여준다
      setBusy(false);
    }
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {}); // 쿠키 삭제 (실패해도 이동)
    router.replace("/login");
  }

  return (
    <main className="login-shell">
      <section className="login-card-pane">
        <div style={S.loginCard}>
          <h1>비밀번호 변경</h1>
          <p style={S.hint}>관리자가 정해 준 임시 비밀번호입니다. 새 비밀번호로 바꾼 뒤 사용할 수 있습니다.</p>
          <form className="field-form field-stack" onSubmit={onSubmit} style={S.formStack}>
            {error && <p role="alert" style={S.loginAlert}>{error}</p>}
            {/* 오류가 있을 때만 표시 (role=alert 는 낭독기가 바로 읽는다) */}
            <Field label="현재(임시) 비밀번호"><input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} required autoFocus autoComplete="current-password" style={S.blockFull} />
            </Field>
            <Field label="새 비밀번호 (8자 이상)"><input type="password" value={next} onChange={(e) => setNext(e.target.value)} required minLength={8} autoComplete="new-password" style={S.blockFull} />
            </Field>
            <Field label="새 비밀번호 확인"><input type="password" value={again} onChange={(e) => setAgain(e.target.value)} required autoComplete="new-password" style={S.blockFull} />
            </Field>
            <button type="submit" disabled={busy} style={S.loginSubmit}>{busy ? "변경 중…" : "비밀번호 변경"}</button>
          </form>
          <p style={{ marginTop: "var(--space-md)" }}><button type="button" onClick={logout}>로그아웃</button></p>
        </div>
      </section>
    </main>
  );
}
