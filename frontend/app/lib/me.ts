"use client"; // 브라우저에서만 쓰는 코드 (React 상태 공유)

import { createContext, useContext } from "react"; // 화면 여러 곳에 같은 값을 나눠 주는 도구

// GET /api/v1/me 응답 모양
export type Me = {
  name: string; // 내 이름
  email: string; // 내 이메일
  role: "ADMIN" | "STAFF"; // 역할
  company: { id: number; name: string }; // 소속 회사
};

export const ROLE_LABEL: Record<Me["role"], string> = { ADMIN: "관리자", STAFF: "담당자" }; // 화면에 보일 역할 이름

export const MeContext = createContext<Me | null>(null); // 로그인한 사용자 정보를 담는 상자 (레이아웃이 채운다)

// 로그인 후 화면에서 내 정보를 꺼내 쓰는 함수. 레이아웃이 로그인을 확인하기 전에는 null 이다
export function useMe(): Me | null {
  return useContext(MeContext); // 상자에서 꺼낸다
}
