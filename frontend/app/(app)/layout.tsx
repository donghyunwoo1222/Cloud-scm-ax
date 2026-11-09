"use client"; // 로그인 확인·메뉴·로그아웃을 브라우저에서 처리

import Link from "next/link"; // 화면 이동 링크
import { usePathname, useRouter } from "next/navigation"; // 지금 주소(현재 메뉴 표시), 로그아웃 후 이동
import { ReactNode, Suspense, useCallback, useEffect, useRef, useState } from "react"; // 자식 화면 타입, 주소 읽는 부품 감싸기, 함수 고정, 처음·변경 때 실행, 포커스용 ref, 상태

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
    { href: "/sales-import", label: "판매 가져오기" },
    { href: "/receipt-import", label: "품목·입고 가져오기" },
  ] },
  { title: "구매 업무", links: [ // 발주 흐름: 추천 → 발주서 → 거래처
    { href: "/recommendations", label: "발주 추천" },
    { href: "/purchase-orders", label: "발주" },
    { href: "/suppliers", label: "공급업체" },
  ] },
  { title: "회사", links: [{ href: "/company", label: "회사 정보" }] }, // 담당자는 읽기만(수정은 서버가 관리자만 허용)
  { title: "관리", adminOnly: true, links: [{ href: "/users", label: "사용자 관리" }] }, // 관리자에게만 보이는 그룹
];

// 지금 주소에 해당하는 메뉴 이름 (모바일 앱바에 "지금 어느 화면인지" 보여 준다). 없으면 서비스 이름
function currentLabel(pathname: string) {
  for (const group of MENU) {
    for (const item of group.links) {
      if (pathname === item.href || pathname.startsWith(`${item.href}/`)) return item.label; // 예) /purchase-orders/3 → "발주"
    }
  }
  return "Cloud SCM"; // 메뉴에 없는 주소
}

// 앱바의 현재 화면 이름 (주소를 읽는 부분만 따로 떼어 Suspense 로 감쌀 수 있게 했다)
function CurrentTitle() {
  return currentLabel(usePathname()); // 지금 주소에 맞는 메뉴 이름
}

// 내 정보 표시: 데스크톱 상단 바(inline 한 줄)와 모바일 드로어(stacked 두 줄)가 같은 내용을 같이 쓴다
function UserSummary({ me, stacked }: { me: Me; stacked?: boolean }) {
  return stacked ? (
    <div className="drawer-user-info">
      <strong>{me.name}</strong>
      <span>{me.company.name} · {ROLE_LABEL[me.role]}</span>
    </div>
  ) : (
    <span>{me.name} · {me.company.name} · {ROLE_LABEL[me.role]}</span> // 예) gana-admin · 가나패션(시드) · 관리자
  );
}

// 아이콘은 글자가 이미 버튼 이름(aria-label)이라 보조기기에서는 숨긴다
function MenuIcon({ close }: { close?: boolean }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      {close ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
    </svg>
  );
}

// 로그인 후 화면들(app/(app)/ 아래)을 감싸는 틀: 로그인 확인 → 사이드 메뉴(모바일은 드로어)·상단 바·앱바 → 각 화면
export default function AppLayout({ children }: { children: ReactNode }) {
  const router = useRouter(); // 로그아웃 후 이동
  const [me, setMe] = useState<Me | null>(null); // 내 정보 (불러오기 전에는 null)
  const [failed, setFailed] = useState(false); // 로그인 확인이 401 이 아닌 이유(네트워크·서버 오류)로 실패했는지
  const [attempt, setAttempt] = useState(0); // "다시 시도" 를 누를 때마다 올려 확인을 다시 한다
  const [menuOpen, setMenuOpen] = useState(false); // 좁은 화면에서 드로어가 열려 있는지
  // 넓은 화면에서 사이드 메뉴를 접었는지(접으면 햄버거만 남는 얇은 띠). 다음에 열어도 유지하도록 브라우저에 기억한다.
  // 메뉴는 로그인 확인 뒤에야 그려져 서버 화면과 어긋나지 않으므로 처음 값을 바로 읽어도 된다. 저장소를 못 쓰면(시크릿 창 등) 그냥 펼친 채로 시작한다
  const [collapsed, setCollapsed] = useState(() => {
    try { return typeof window !== "undefined" && window.localStorage.getItem("sidebar-collapsed") === "1"; } catch { return false; }
  });
  const openButton = useRef<HTMLButtonElement>(null); // 앱바의 햄버거 버튼 (닫을 때 포커스를 돌려준다)
  const closeButton = useRef<HTMLButtonElement>(null); // 드로어의 닫기 버튼 (열 때 포커스를 옮긴다)
  const restoreFocus = useRef(false); // 닫은 뒤 햄버거로 포커스를 돌려줄지 (닫는 순간에는 뒤 화면이 아직 inert 라 포커스가 안 들어간다)

  useEffect(() => {
    // 화면이 열릴 때(그리고 다시 시도할 때): 로그인 상태 확인. 로그인 안 했으면 api 함수가 401 을 받아 로그인 화면으로 보낸다
    api<Me>("/me").then(setMe).catch((e) => {
      if (!(e instanceof ApiError && e.status === 401)) setFailed(true); // 401 은 api 함수가 이동시키니 그 밖의 실패만 안내한다
    });
  }, [attempt]);

  // 드로어를 닫는다. 버튼·Esc·배경으로 닫을 때는 햄버거로 포커스를 돌려주고, 메뉴 링크로 이동할 때는 돌려주지 않는다
  const closeMenu = useCallback((returnFocus: boolean) => {
    restoreFocus.current = returnFocus; // 실제 포커스 이동은 아래 effect 가 화면이 바뀐 뒤에 한다
    setMenuOpen(false);
  }, []);

  useEffect(() => {
    if (menuOpen || !restoreFocus.current) return; // 열려 있거나, 링크 이동으로 닫은 경우는 건너뛴다
    restoreFocus.current = false;
    openButton.current?.focus(); // 뒤 화면의 inert 가 풀린 뒤라 포커스가 들어간다
  }, [menuOpen]);

  useEffect(() => {
    if (!menuOpen) return; // 닫혀 있으면 아래 장치는 필요 없다
    closeButton.current?.focus(); // 열면 포커스를 드로어 안(닫기 버튼)으로 옮긴다
    const html = document.documentElement; // 뒤 화면 스크롤을 잠그려고 html 에 overflow 를 준다
    const before = html.style.overflow; // 원래 값 (닫을 때 되돌린다)
    html.style.overflow = "hidden";
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") closeMenu(true); }; // Esc 로 닫기
    const wide = window.matchMedia("(min-width: 730px)"); // 열어 둔 채 화면이 넓어지면(가로 회전 등) 드로어를 닫는다
    const onWide = () => { if (wide.matches) closeMenu(false); };
    document.addEventListener("keydown", onKey);
    wide.addEventListener("change", onWide);
    return () => { // 닫히거나 화면을 떠날 때 모두 원래대로
      html.style.overflow = before;
      document.removeEventListener("keydown", onKey);
      wide.removeEventListener("change", onWide);
    };
  }, [menuOpen, closeMenu]);

  function toggleSidebar() {
    const next = !collapsed;
    setCollapsed(next);
    try { window.localStorage.setItem("sidebar-collapsed", next ? "1" : "0"); } catch { /* 저장 실패해도 이번 화면에서는 접힌다 */ }
  }

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
        <aside id="app-drawer" className="sidebar" style={S.sidebar} data-open={menuOpen} data-collapsed={collapsed} aria-label="메뉴">
          {/* 데스크톱: 왼쪽에 항상 보이는 사이드 메뉴. 모바일(730px 미만): 햄버거로 여는 드로어 (화면 위로 덮이고 본문은 밀리지 않는다) */}
          <div className="sidebar-heading">
            <button className="sidebar-toggle" type="button" aria-label={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
              aria-expanded={!collapsed} aria-controls="app-nav" onClick={toggleSidebar}>
              <MenuIcon />
              {/* 데스크톱 전용 햄버거: 누르면 메뉴를 접고 펼친다. 모바일에서는 숨기고 앱바 햄버거·드로어를 쓴다 */}
            </button>
            <div className="sidebar-brand">Cloud SCM</div>
            <button className="drawer-close" ref={closeButton} type="button" aria-label="메뉴 닫기" onClick={() => closeMenu(true)}>
              <MenuIcon close />
            </button>
          </div>
          <div className="drawer-user">
            <UserSummary me={me} stacked />
            {/* 모바일에서는 내 정보가 상단 바 대신 여기에 있다 */}
          </div>
          <Suspense fallback={null}>
            <SideNav isAdmin={me.role === "ADMIN"} onNavigate={() => closeMenu(false)} />
          </Suspense>
          {/* 지금 주소를 읽는 부품은 Suspense 로 감싸야 Next.js 16 빌드가 된다 */}
          <div className="drawer-logout">
            <button type="button" onClick={logout}>로그아웃</button>
            {/* 위험한 동작은 메뉴와 구분선으로 떨어뜨려 맨 아래에 둔다 */}
          </div>
        </aside>
        )}
        {me && (
        <div className="drawer-scrim" data-open={menuOpen} aria-hidden="true" onClick={() => closeMenu(true)} />
        )}
        {/* 드로어 뒤의 반투명 배경: 누르면 닫힌다 (키보드는 Esc·닫기 버튼이 있어 탭 순서에서 뺀다) */}
        <div style={S.content} inert={menuOpen}>
          {/* inert: 드로어가 열려 있는 동안 뒤 화면은 클릭·Tab·낭독 대상에서 빠진다 (포커스가 드로어 밖으로 새지 않는다) */}
          {me && (
          <div className="app-bar">
            <button className="app-bar-menu" ref={openButton} type="button" aria-label="메뉴 열기"
              aria-expanded={menuOpen} aria-controls="app-drawer" onClick={() => setMenuOpen(true)}>
              <MenuIcon />
            </button>
            <span className="app-bar-title">
              <Suspense fallback="Cloud SCM"><CurrentTitle /></Suspense>
              {/* 주소를 읽는 부품은 Suspense 로 감싸야 Next.js 16 빌드가 된다 */}
            </span>
          </div>
          )}
          {/* 모바일 앱바: 56px 한 줄 (햄버거 + 현재 화면 이름). 데스크톱에서는 숨긴다 */}
          {me && (
          <header className="desktop-topbar" style={S.topbar}>
            <UserSummary me={me} />
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
function SideNav({ isAdmin, onNavigate }: { isAdmin: boolean; onNavigate: () => void }) {
  const pathname = usePathname(); // 지금 주소 (예: /purchase-orders/3 → "발주" 메뉴를 현재 메뉴로)
  return (
    <nav id="app-nav" className="side-nav" aria-label="주 메뉴" style={S.sideNav}>
      {MENU.filter((group) => !group.adminOnly || isAdmin).map((group) => (
        // 그룹 하나 = (제목) + 링크들. 제목이 있으면 낭독기가 "재고 업무 그룹" 처럼 읽도록 묶는다
        <div key={group.links[0].href} style={S.sideNav} role={group.title ? "group" : undefined} aria-label={group.title}>
          {group.title && <p style={S.navGroupTitle} aria-hidden="true">{group.title}</p>}
          {/* 그룹 제목은 눈으로 보는 용도 (낭독기는 위의 aria-label 로 읽는다) */}
          {group.links.map((item) => (
            <Link key={item.href} href={item.href} onNavigate={onNavigate}
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
