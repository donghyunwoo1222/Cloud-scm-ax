"use client"; // 로그인 확인·메뉴·로그아웃을 브라우저에서 처리

import Link from "next/link"; // 화면 이동 링크
import { useRouter } from "next/navigation"; // 로그아웃 후 이동
import { ReactNode, useEffect, useState } from "react"; // 자식 화면 타입, 처음 한 번 실행, 상태

import { api } from "../lib/api"; // 공통 API 호출 함수
import { Me, MeContext, ROLE_LABEL } from "../lib/me"; // 내 정보 모양·공유 상자·역할 이름

// 상단 메뉴. adminOnly 는 관리자에게만 "보이게" 하는 표시일 뿐이다.
// 메뉴를 숨기는 건 편의이고, 실제 권한은 서버가 검사한다(담당자가 주소를 직접 쳐도 API 가 403 을 준다).
const MENU = [
  { href: "/dashboard", label: "대시보드" },
  { href: "/inventory", label: "재고 현황" },
  { href: "/products", label: "품목" },
  { href: "/suppliers", label: "공급업체" },
  { href: "/receipts", label: "입고 등록" },
  { href: "/shipments", label: "출고 등록" },
  { href: "/purchase-orders", label: "발주" },
  { href: "/users", label: "사용자 관리", adminOnly: true },
];

// 로그인 후 화면들(app/(app)/ 아래)을 감싸는 틀: 로그인 확인 → 상단 바 → 각 화면
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter(); // 로그아웃 후 이동
  const [me, setMe] = useState<Me | null>(null); // 내 정보 (불러오기 전에는 null)

  useEffect(() => {
    // 화면이 열릴 때 한 번: 로그인 상태 확인. 로그인 안 했으면 api 함수가 401 을 받아 로그인 화면으로 보낸다
    api<Me>("/me").then(setMe).catch(() => {});
  }, []);

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {}); // 서버가 쿠키를 지운다 (실패해도 로그인 화면으로)
    router.replace("/login"); // 로그인 화면으로
  }

  return (
    <MeContext.Provider value={me}>
      {/* 아래 화면들이 useMe() 로 내 정보를 꺼내 쓸 수 있게 (확인 전에는 null) */}
      {!me && <p style={{ padding: "2rem" }}>불러오는 중…</p>}
      {/* 로그인 확인 전 안내 */}
      {me && (
      <header style={{ display: "flex", flexWrap: "wrap", gap: "1rem", alignItems: "center", padding: "0.75rem 1.5rem", borderBottom: "1px solid #ccc" }}>
        <nav style={{ display: "flex", flexWrap: "wrap", gap: "1rem" }}>
          {MENU.filter((item) => !item.adminOnly || me.role === "ADMIN").map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
          {/* 관리자 전용 메뉴는 관리자에게만 보인다 (편의일 뿐, 권한은 서버가 검사) */}
        </nav>
        <span style={{ marginLeft: "auto" }}>
          {me.name} · {me.company.name} · {ROLE_LABEL[me.role]}
        </span>
        {/* 내 이름·회사명·역할 */}
        <button type="button" onClick={logout}>
          로그아웃
        </button>
      </header>
      )}
      <main hidden={!me} style={{ padding: "1.5rem" }}>{children}</main>
      {/* 각 화면 내용. 로그인 확인 전에도 그려 두되(Next.js 가 화면 구조를 미리 검사할 수 있게) 확인 전까지는 숨긴다.
          데이터는 화면이 아니라 서버가 지킨다: 로그인 안 한 상태의 API 호출은 401 → 로그인 화면 */}
    </MeContext.Provider>
  );
}
