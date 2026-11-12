"use client"; // 브라우저에서만 쓰는 코드 (React 상태 공유)

import { createContext, useContext } from "react"; // 화면 여러 곳에 같은 값을 나눠 주는 도구

// GET /api/v1/me 응답 모양
export type Me = {
  name: string; // 내 이름
  email: string; // 내 이메일
  role: "ADMIN" | "STAFF"; // 역할
  company: { id: number; name: string }; // 소속 회사
  must_change_password: boolean; // 참이면 비밀번호를 바꾸기 전에는 다른 화면을 못 쓴다
  otp_notice?: string | null; // 유예 중 관리자에게 보여 줄 메일 인증코드 안내 (로그인 응답에만 있고 /me 에는 null, #179)
};

export const NOTICE_KEY = "otp-notice"; // 로그인 화면이 유예 안내 문장을 레이아웃 배너로 넘길 때 쓰는 sessionStorage 키

export const ROLE_LABEL: Record<Me["role"], string> = { ADMIN: "관리자", STAFF: "담당자" }; // 화면에 보일 역할 이름

export const MeContext = createContext<Me | null>(null); // 로그인한 사용자 정보를 담는 상자 (레이아웃이 채운다)

// 로그인 후 화면에서 내 정보를 꺼내 쓰는 함수. 레이아웃이 로그인을 확인하기 전에는 null 이다
export function useMe(): Me | null {
  return useContext(MeContext); // 상자에서 꺼낸다
}
