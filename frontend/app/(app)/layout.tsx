"use client"; // 로그인 확인·메뉴·로그아웃을 브라우저에서 처리

import Link from "next/link"; // 화면 이동 링크
import { useRouter } from "next/navigation"; // 로그아웃 후 이동
import { ReactNode, useEffect, useState } from "react"; // 자식 화면 타입, 처음 한 번 실행, 상태

import { ApiError, api } from "../lib/api"; // 공통 API 호출 함수·오류 종류
import { Me, MeContext, ROLE_LABEL } from "../lib/me"; // 내 정보 모양·공유 상자·역할 이름
import { S } from "../lib/styles"; // 화면 공통 스타일

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
  { href: "/recommendations", label: "발주 추천" },
  { href: "/users", label: "사용자 관리", adminOnly: true },
];

// 로그인 후 화면들(app/(app)/ 아래)을 감싸는 틀: 로그인 확인 → 상단 바 → 각 화면
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter(); // 로그아웃 후 이동
  const [me, setMe] = useState<Me | null>(null); // 내 정보 (불러오기 전에는 null)
  const [failed, setFailed] = useState(false); // 로그인 확인이 401 이 아닌 이유(네트워크·서버 오류)로 실패했는지
  const [attempt, setAttempt] = useState(0); // "다시 시도" 를 누를 때마다 올려 확인을 다시 한다

  useEffect(() => {
    // 화면이 열릴 때(그리고 다시 시도할 때): 로그인 상태 확인. 로그인 안 했으면 api 함수가 401 을 받아 로그인 화면으로 보낸다
    api<Me>("/me").then(setMe).catch((e) => {
      if (!(e instanceof ApiError && e.status === 401)) setFailed(true); // 401 은 api 함수가 이동시키니 그 밖의 실패만 안내한다
    });
  }, [attempt]);

  function retry() {
    setFailed(false); // 안내를 지우고 "불러오는 중…" 으로
    setAttempt((n) => n + 1); // 확인 다시 실행
  }

  async function logout() {
    await api("/auth/logout", { method: "POST" }).catch(() => {}); // 서버가 쿠키를 지운다 (실패해도 로그인 화면으로)
    router.replace("/login"); // 로그인 화면으로
  }

  return (
    <MeContext.Provider value={me}>
      {/* 아래 화면들이 useMe() 로 내 정보를 꺼내 쓸 수 있게 (확인 전에는 null) */}
      {!me && !failed && <p style={S.pad2}>불러오는 중…</p>}
      {!me && failed && (
        <div style={S.pad2}>
          <p role="alert">로그인 상태를 확인하지 못했습니다. 잠시 뒤 다시 시도해 주세요.</p>
          <button type="button" onClick={retry}>다시 시도</button>
        </div>
      )}
      {/* 로그인 확인 전 안내 */}
      {me && (
      <header style={S.header}>
        <nav style={S.nav}>
          {MENU.filter((item) => !item.adminOnly || me.role === "ADMIN").map((item) => (
            <Link key={item.href} href={item.href}>
              {item.label}
            </Link>
          ))}
          {/* 관리자 전용 메뉴는 관리자에게만 보인다 (편의일 뿐, 권한은 서버가 검사) */}
        </nav>
        <span style={S.pushRight}>
          {me.name} · {me.company.name} · {ROLE_LABEL[me.role]}
        </span>
        {/* 내 이름·회사명·역할 */}
        <button type="button" onClick={logout}>
          로그아웃
        </button>
      </header>
      )}
      <main hidden={!me} style={S.main}>{children}</main>
      {/* 각 화면 내용. 로그인 확인 전에도 그려 두되(Next.js 가 화면 구조를 미리 검사할 수 있게) 확인 전까지는 숨긴다.
          데이터는 화면이 아니라 서버가 지킨다: 로그인 안 한 상태의 API 호출은 401 → 로그인 화면 */}
    </MeContext.Provider>
  );
}
