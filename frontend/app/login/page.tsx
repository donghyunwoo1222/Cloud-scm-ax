"use client"; // 입력·클릭을 다루는 화면이라 브라우저에서 실행

import { useRouter } from "next/navigation"; // 화면 이동 도구
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react"; // 폼 제출 이벤트, 키 이벤트, 처음 한 번 실행, 참조, 화면 상태

import { Field } from "../lib/field"; // 모바일에서 라벨이 테두리에 걸리는 입력 항목
import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { S } from "../lib/styles"; // 화면 공통 스타일

// 왼쪽 소개에 쓰는 세 가지 (실제로 있는 기능만 쓴다)
const INTRO_ITEMS = ["재고 현황과 부족 품목 확인", "발주 추천과 발주서 초안", "입출고 이력 조회"];

// 눈 모양 아이콘 (인라인 SVG). hidden 이 true 면 눈에 빗금을 그어 "숨김 상태"를 나타낸다
function EyeIcon({ hidden }: { hidden: boolean }) {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {/* 눈 바깥 모양 */}
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
      {/* 눈동자 */}
      <circle cx="12" cy="12" r="3" />
      {/* 숨김 상태일 때만 빗금 */}
      {hidden && <path d="M4 4l16 16" />}
    </svg>
  );
}

// 오류 앞에 붙는 느낌표 원 아이콘 (색만으로 구분하지 않으려고 글자와 같이 쓴다)
function AlertIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flexShrink: 0, marginTop: 2 }}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 8v5" />
      <path d="M12 16.5h.01" />
    </svg>
  );
}

// 로그인 화면 (주소 /login)
export default function LoginPage() {
  const router = useRouter(); // 로그인 성공 후 이동에 쓴다
  const [email, setEmail] = useState(""); // 입력한 이메일
  const [password, setPassword] = useState(""); // 입력한 비밀번호
  const [error, setError] = useState(""); // 화면에 보일 오류 문장
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다 (두 번 누르기 방지)
  const [showPassword, setShowPassword] = useState(false); // 비밀번호를 글자로 보여 줄지
  const [capsOn, setCapsOn] = useState(false); // Caps Lock 이 켜져 있는지
  const busyRef = useRef(false); // 상태 갱신 전에 연달아 들어오는 제출을 막는 즉시 표시
  const passwordRef = useRef<HTMLInputElement>(null); // 실패 후 비밀번호 칸에 포커스를 주려고 잡아 둔다

  useEffect(() => {
    // 이미 로그인한 상태로 /login 을 열면 대시보드로 보낸다 (로그인 안 했으면 401 이지만 여기서는 이동하지 않고 그대로 둔다)
    api("/me", { redirectOn401: false }).then(() => router.replace("/dashboard")).catch(() => {});
  }, [router]);

  // 키를 누르거나 뗄 때마다 Caps Lock 상태를 확인한다
  function checkCaps(event: KeyboardEvent<HTMLInputElement>) {
    setCapsOn(event.getModifierState("CapsLock")); // 브라우저가 알려 주는 Caps Lock 켜짐 여부
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault(); // 브라우저 기본 동작(페이지 새로고침)을 막는다
    if (busyRef.current) return; // 이미 요청 중이면 무시
    busyRef.current = true; // 즉시 잠금 표시
    setBusy(true); // 버튼 잠금
    setError(""); // 이전 오류 지우기
    try {
      // 서버가 토큰을 httpOnly 쿠키로 내려준다. 화면 코드는 토큰을 직접 다루지 않는다
      await api("/auth/login", { method: "POST", body: { email, password }, redirectOn401: false });
      setPassword(""); // 로그아웃 뒤 다시 열린 로그인 화면(Next.js 가 상태를 그대로 보관한다)에 이전 비밀번호가 남지 않게 비운다
      setShowPassword(false); // 같은 이유로 "표시" 상태도 되돌린다
      busyRef.current = false; // 같은 이유로 잠금도 풀어 둔다 (안 풀면 로그아웃 후 "로그인 중…" 으로 멈춘다)
      setBusy(false); // 버튼 잠금 해제
      router.replace("/dashboard"); // 성공: 대시보드로 (뒤로 가기로 로그인 화면에 돌아오지 않게 replace)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "로그인하지 못했습니다."); // 서버가 준 문장을 그대로 보여준다
      setPassword(""); // 실패하면 비밀번호만 비운다 (이메일은 그대로)
      busyRef.current = false; // 다시 시도할 수 있게 잠금 해제
      setBusy(false); // 버튼 잠금 해제
      passwordRef.current?.focus(); // 비밀번호 칸으로 바로 돌아가 다시 입력하게 한다
    }
  }

  return (
    <main className="login-shell">
      {/* 넓은 화면: 왼쪽 소개 + 오른쪽 카드 */}
      <section className="login-intro-pane" aria-label="서비스 소개">
        <div style={S.loginIntro}>
          <p style={{ fontSize: "var(--text-lg)", fontWeight: 700 }}>Cloud SCM</p>
          {/* 서비스 이름 */}
          <h2 style={{ fontSize: 28, lineHeight: 1.3, margin: 0 }}>재고·입출고·발주를 한 화면에서</h2>
          {/* 한 줄 설명 */}
          <ul style={S.loginIntroList}>
            {INTRO_ITEMS.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      </section>
      <section className="login-card-pane">
        <div style={S.loginCard}>
          <h1>로그인</h1>
          <form className="field-form field-stack" onSubmit={onSubmit} style={S.formStack}>
            {/* 입력칸을 세로로 쌓는다 */}
            {error && (
              <p role="alert" style={S.loginAlert}>
                <AlertIcon />
                <span>{error}</span>
              </p>
            )}
            {/* 실패 메시지는 폼 맨 위 한 곳에만. role="alert" 는 화면 낭독기가 바로 읽게 한다 */}
            <Field label="이메일"><input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus autoComplete="username" style={S.blockFull} />
            </Field>
            <Field label="비밀번호">
              <span style={S.passwordWrap}>
                <input ref={passwordRef} type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={checkCaps} onKeyUp={checkCaps} onBlur={() => setCapsOn(false)} required autoComplete="current-password" style={{ ...S.blockFull, paddingRight: 40 }} />
                {/* 오른쪽 40px 은 표시/숨김 버튼 자리 */}
                <button type="button" onClick={() => setShowPassword((v) => !v)} aria-label={showPassword ? "비밀번호 숨기기" : "비밀번호 표시"} aria-pressed={showPassword} style={S.passwordToggle}>
                  <EyeIcon hidden={showPassword} />
                </button>
              </span>
            </Field>
            {capsOn && <p style={{ ...S.hint, fontSize: "var(--text-xs)", marginTop: -4 }}>Caps Lock이 켜져 있습니다</p>}
            {/* Caps Lock 경고는 비밀번호 칸 바로 아래 */}
            <button type="submit" disabled={busy} style={S.loginSubmit}>
              {busy ? "로그인 중…" : "로그인"}
            </button>
          </form>
          <p style={{ ...S.hint, fontSize: "var(--text-xs)", marginTop: "var(--space-md)" }}>계정은 회사 관리자가 만들어 줍니다.</p>
        </div>
      </section>
    </main>
  );
}
