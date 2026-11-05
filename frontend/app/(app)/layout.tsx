"use client"; // 로그인 확인·메뉴·로그아웃을 브라우저에서 처리

import Link from "next/link"; // 화면 이동 링크
import { usePathname, useRouter } from "next/navigation"; // 지금 주소(현재 메뉴 표시), 로그아웃 후 이동
import { ReactNode, Suspense, useEffect, useState } from "react"; // 자식 화면 타입, 주소 읽는 부품 감싸기, 처음 한 번 실행, 상태

import { ApiError, api } from "../lib/api"; // 공통 API 호출 함수·오류 종류
import { Me, MeContext, ROLE_LABEL } from "../lib/me"; // 내 정보 모양·공유 상자·역할 이름
import { S } from "../lib/styles"; // 화면 공통 스타일

// 사이드 메뉴를 업무별 그룹으로 나눈다. title 이 없는 그룹(대시보드)은 제목 없이 맨 위에 놓인다.
// adminOnly 는 관리자에게만 그룹째 "보이게" 하는 표시일 뿐이다.
// 메뉴를 숨기는 건 편의이고, 실제 권한은 서버가 검사한다(담당자가 주소를 직접 쳐도 API 가 403 을 준다).
const MENU = [
  { links: [{ href: "/dashboard", label: "대시보드" }] }, // 그룹 밖: 첫 화면
  { title: "재고 업무", links: [ // 매일 하는 재고 일
    { href: "/inventory", label: "재고 현황" },
    { href: "/products", label: "품목" },
    { href: "/receipts", label: "입고 등록" },
    { href: "/shipments", label: "출고 등록" },
  ] },
  { title: "구매 업무", links: [ // 발주 흐름: 추천 → 발주서 → 거래처
    { href: "/recommendations", label: "발주 추천" },
    { href: "/purchase-orders", label: "발주" },
    { href: "/suppliers", label: "공급업체" },
  ] },
  { title: "관리", adminOnly: true, links: [{ href: "/users", label: "사용자 관리" }] }, // 관리자에게만 보이는 그룹
];

// 로그인 후 화면들(app/(app)/ 아래)을 감싸는 틀: 로그인 확인 → 사이드 메뉴·상단 바 → 각 화면
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
      <div style={S.shell}>
        {me && (
        <aside className="sidebar" style={S.sidebar}>
          <div style={S.brand}>Cloud SCM</div>
          <Suspense fallback={null}>
            <SideNav isAdmin={me.role === "ADMIN"} />
          </Suspense>
          {/* 지금 주소를 읽는 부품은 Suspense 로 감싸야 Next.js 16 빌드가 된다 */}
        </aside>
        )}
        <div style={S.content}>
          {me && (
          <header style={S.topbar}>
            <span>
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
        </div>
      </div>
    </MeContext.Provider>
  );
}

// 사이드 메뉴 링크 목록. 지금 화면의 메뉴에 aria-current="page" 를 달아 표시한다(색은 globals.css 의 .side-nav)
function SideNav({ isAdmin }: { isAdmin: boolean }) {
  const pathname = usePathname(); // 지금 주소 (예: /purchase-orders/3 → "발주" 메뉴를 현재 메뉴로)
  return (
    <nav className="side-nav" aria-label="주 메뉴" style={S.sideNav}>
      {MENU.filter((group) => !group.adminOnly || isAdmin).map((group) => (
        // 그룹 하나 = (제목) + 링크들. 제목이 있으면 낭독기가 "재고 업무 그룹" 처럼 읽도록 묶는다
        <div key={group.links[0].href} style={S.sideNav} role={group.title ? "group" : undefined} aria-label={group.title}>
          {group.title && <p style={S.navGroupTitle} aria-hidden="true">{group.title}</p>}
          {/* 그룹 제목은 눈으로 보는 용도 (낭독기는 위의 aria-label 로 읽는다) */}
          {group.links.map((item) => (
            <Link key={item.href} href={item.href}
              aria-current={pathname === item.href || pathname.startsWith(`${item.href}/`) ? "page" : undefined}>
              {item.label}
            </Link>
          ))}
        </div>
      ))}
      {/* 관리자 전용 그룹은 관리자에게만 보인다 (편의일 뿐, 권한은 서버가 검사) */}
    </nav>
  );
}
