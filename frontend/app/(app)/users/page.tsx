"use client"; // 내 역할(useMe)을 읽는 화면이라 브라우저에서 실행

import { useMe } from "../../lib/me"; // 로그인한 내 정보
import ComingSoon from "../coming-soon"; // "준비 중" 자리

// 사용자 관리 화면 (주소 /users)
export default function UsersPage() {
  const me = useMe(); // 내 역할 확인
  if (!me) return null; // 로그인 확인 전 (레이아웃이 숨겨 둔 상태)
  // 담당자가 주소를 직접 쳐서 들어온 경우 안내만 한다. 실제 차단은 서버(/api/v1/users 가 403)가 한다
  if (me.role !== "ADMIN") return <p role="alert">관리자만 볼 수 있는 화면입니다.</p>;
  return <ComingSoon title="사용자 관리" issue="#59" />;
}
