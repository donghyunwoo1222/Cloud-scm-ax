"use client"; // 입력·타이머를 다루는 화면이라 브라우저에서 실행

import { FormEvent, useEffect, useRef, useState } from "react"; // 폼 제출 이벤트, 처음 한 번 실행, 참조, 화면 상태

import { api, ApiError } from "../lib/api"; // 공통 API 호출 함수
import { Field } from "../lib/field"; // 라벨이 붙은 입력 항목
import { Me } from "../lib/me"; // 로그인 성공 응답 모양
import { S } from "../lib/styles"; // 화면 공통 스타일

// 서버가 "코드 단계로 가라" 고 알려 주는 응답 (login·resend 공통, backend login_otp.challenge_out)
export type Challenge = {
  otp_required: true; // 이 응답이면 항상 true (직원·유예 중 관리자의 로그인 응답에는 이 칸이 없다)
  code_sent: boolean; // false = 60초 안에 다시 로그인해 새 메일을 보내지 않았다
  message: string; // 화면에 그대로 보여 줄 안내
  expires_in: number; // 코드가 몇 초 더 유효한지
  resend_after: number; // 몇 초 뒤 재발송할 수 있는지
};

// 이 단계에서 비밀번호 단계로 돌아가야 하는 서버 오류 (임시 토큰이 없거나 만료, 5번 실패, 로그인 잠금, 재발송 한도)
const RESTART_CODES = ["OTP_RESTART", "UNAUTHENTICATED", "TOO_MANY_ATTEMPTS"];

// 메일 인증코드 입력 단계 (로그인 화면 안에서 비밀번호 단계 다음에 보인다)
export function OtpStep({ challenge, onSuccess, onRestart }: {
  challenge: Challenge; // 처음 받은 코드 단계 응답
  onSuccess: (me: Me) => void; // 코드가 맞아 로그인된 경우
  onRestart: (message: string) => void; // 비밀번호 단계로 돌아가야 할 때 (message 가 빈 문자열이면 안내 없이)
}) {
  const [code, setCode] = useState(""); // 입력한 6자리
  const [error, setError] = useState(""); // 화면에 보일 오류 문장
  const [info, setInfo] = useState(challenge.message); // 서버가 준 안내 문장 (메일을 보냈다 등)
  const [busy, setBusy] = useState(false); // 요청 중이면 버튼을 잠근다
  const [deadline, setDeadline] = useState(() => Date.now() + challenge.resend_after * 1000); // 재발송이 가능해지는 시각 (ms)
  const [now, setNow] = useState(() => Date.now()); // 화면이 마지막으로 읽은 현재 시각 (1초마다 다시 읽는다)
  const busyRef = useRef(false); // 상태 갱신 전에 연달아 들어오는 요청을 막는 즉시 표시 (코드 확인·재발송이 함께 쓴다)
  const inputRef = useRef<HTMLInputElement>(null); // 입력칸으로 포커스를 옮길 때 쓴다

  const remaining = Math.max(0, Math.ceil((deadline - now) / 1000)); // 남은 초: 숫자를 빼지 않고 마감 시각과 현재 시각의 차이로 계산한다 (탭이 늦게 돌아도 맞는다)

  useEffect(() => {
    inputRef.current?.focus(); // 코드 단계가 열리면 입력칸으로 포커스
  }, []);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000); // 1초마다 현재 시각만 다시 읽는다
    return () => clearInterval(timer); // 화면을 떠나면 멈춘다
  }, []);

  // 요청 하나를 한 번에 하나만 보낸다. 서버 오류 처리는 두 요청이 같다
  async function run(task: () => Promise<void>) {
    if (busyRef.current) return; // 이미 요청 중이면 무시
    busyRef.current = true; // 즉시 잠금
    setBusy(true);
    setError(""); // 이전 오류 지우기
    try {
      await task();
    } catch (e) {
      if (!(e instanceof ApiError)) setError("요청을 처리하지 못했습니다.");
      else if (RESTART_CODES.includes(e.code)) { onRestart(e.message); return; } // 이 컴포넌트는 곧 사라진다 (잠금은 새로 열릴 때 다시 초기화된다)
      else if (e.code === "OTP_RESEND_WAIT") { // 재발송이 너무 이르다: 서버가 알려 준 초로 카운트다운을 다시 맞춘다
        const wait = (e.details as { retry_after?: number } | null)?.retry_after;
        if (typeof wait === "number") { setDeadline(Date.now() + wait * 1000); setNow(Date.now()); }
        setError(e.message);
      } else {
        setError(e.message); // 틀린 코드·만료·메일 서비스 장애 등은 서버 문장을 그대로 보여 준다
        if (e.code === "OTP_INVALID") { setCode(""); inputRef.current?.focus(); } // 틀리면 입력칸만 비우고 바로 다시 입력하게 한다
      }
    }
    busyRef.current = false; // 다시 시도할 수 있게 잠금 해제
    setBusy(false);
  }

  function submit(event: FormEvent) {
    event.preventDefault(); // 페이지 새로고침 막기
    if (code.length !== 6) return; // 6자리가 아니면 보내지 않는다
    void run(async () => {
      // otp_pending 쿠키는 브라우저가 이 경로 요청에 자동으로 붙인다 (화면은 토큰을 다루지 않는다)
      const me = await api<Me>("/auth/otp/verify", { method: "POST", body: { code }, redirectOn401: false });
      onSuccess(me); // 성공: 로그인 화면이 대시보드로 보낸다
    });
  }

  function resend() {
    void run(async () => {
      const next = await api<Challenge>("/auth/otp/resend", { method: "POST", redirectOn401: false });
      setInfo(next.message); // 새 안내
      setDeadline(Date.now() + next.resend_after * 1000); // 새 카운트다운
      setNow(Date.now());
      setCode(""); // 옛 코드는 무효라 비운다
      inputRef.current?.focus();
    });
  }

  function cancel() {
    // 임시 토큰 쿠키를 지운다. 로그인 토큰 없이 불려도 되고, 실패해도 화면은 그대로 처음으로 돌아간다
    api("/auth/logout", { method: "POST", redirectOn401: false }).catch(() => {});
    onRestart("");
  }

  return (
    <form className="field-form field-stack" onSubmit={submit} style={S.formStack}>
      {/* 안내·카운트다운은 aria-live 영역: 바뀌면 화면 낭독기가 읽는다 */}
      <p role="status" aria-live="polite" style={S.hint}>
        {info}{remaining > 0 ? " 코드를 다시 받으려면 잠시 기다려 주세요." : " 코드를 다시 받을 수 있습니다."}
      </p>
      {/* 오류는 즉시 읽히도록 role="alert" (기존 로그인 오류와 같다) */}
      {error && <p role="alert" style={S.loginAlert}><span>{error}</span></p>}
      <Field label="인증코드 (6자리)">
        <input ref={inputRef} type="text" inputMode="numeric" pattern="[0-9]*" maxLength={6} value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))} // 숫자만, 6자리까지 (붙여넣은 "123 456" 도 123456 으로)
          autoComplete="one-time-code" required style={S.blockFull} />
      </Field>
      <button type="submit" disabled={busy || code.length !== 6} style={S.loginSubmit}>{busy ? "확인 중…" : "확인"}</button>
      <button type="button" onClick={resend} disabled={busy || remaining > 0} style={S.loginSubmit}>
        {remaining > 0 ? `코드 다시 받기 (${remaining}초)` : "코드 다시 받기"}
      </button>
      <button type="button" onClick={cancel} style={S.loginSubmit}>처음으로</button>
    </form>
  );
}
