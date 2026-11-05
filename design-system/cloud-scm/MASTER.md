# Design System Master File

> **LOGIC:** When building a specific page, first check `design-system/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file.
> If not, strictly follow the rules below.

---

**Project:** Cloud SCM
**Generated:** 2026-11-05 12:02:44
**Category:** SaaS (General)
**Design Dials:** Variance 2/10 (Centered / Minimal) | Motion 2/10 (Subtle) | Density 7/10 (Standard)

---

## Cloud SCM 조정 (이 절이 아래 자동 생성 내용보다 우선)

자동 생성 결과 중 우리 제품(데스크톱 우선 업무 도구, 표 중심, 다크 모드 없음)과 맞지 않는 부분을 바로잡는다. 출처 표시: [DB] = 스킬 검색 결과, [기본값] = 검색 결과가 없어 일반 원칙으로 정한 것.

**스택 제약**: Tailwind, shadcn/ui, GSAP, 아이콘·차트 라이브러리를 새로 넣지 않는다. 토큰은 `frontend/app/globals.css`의 CSS 변수로, 공통 스타일은 `frontend/app/lib/styles.ts`의 `S`로 둔다.

**쓰지 않는 것**
- 아래 "Page Pattern"의 Hero + Features + CTA: 랜딩 페이지용이라 업무 화면에 맞지 않다.
- 아래 "Motion"의 GSAP Scroll Reveal: 새 라이브러리이고, 표 화면에 스크롤 등장 효과는 필요 없다. 모션은 hover·focus 색 전환 150~200ms 정도만 쓴다.
- Accent `#EA580C`(주황): 파란 포인트 하나로 간다. 강조가 필요하면 Primary를 쓴다.
- 다크 모드: 지원하지 않는다. globals.css의 `prefers-color-scheme: dark` 블록은 디자인 적용 때 지운다.
- 폰트 Plus Jakarta Sans: 한글 글리프가 없다.

**폰트** [DB: Korean Modern]
- 본문·제목: `Noto Sans KR` (400 / 500 / 700). Next.js 내장 `next/font/google`로 불러오면 새 의존성이 없다.
- 대체: `Pretendard`는 DB에 없다(Google Fonts 아님). 쓰려면 폰트 파일을 직접 두어야 하므로 지금은 대체 순서에만 둔다.
- `font-family: "Noto Sans KR", Pretendard, -apple-system, "Malgun Gothic", sans-serif;`
- 숫자 열: `font-variant-numeric: tabular-nums;` (숫자 폭을 같게 해 자릿수가 세로로 맞는다) [기본값]

**간격** [DB, 단 density 7은 표준 눈금]
- 다이얼 7은 "Standard"로 분류되어 4/8/16/24/32/48/64px 눈금이 나왔다(촘촘한 눈금은 8 이상). 업무 화면은 4·8·16·24px만 주로 쓰고 48·64px는 쓰지 않는다.
- 표 행 높이 40px 안팎(셀 위아래 8px), 카드 안쪽 16~24px.

**표 규칙** [기본값 — DB 검색 "data table numeric alignment"에서 정렬 규칙은 나오지 않음]
- 숫자 열(수량, 재고, 일평균, 추천 수량, 금액)은 오른쪽 정렬, 머리 칸도 같이 오른쪽 정렬. 글자 열은 왼쪽 정렬.
- 머리 줄: 배경 `--color-muted`, 글자 `--color-muted-foreground` 500 굵기, 아래 테두리 `--color-border`.
- 본문 줄 구분선은 `--color-border` 1px, 마우스 올린 줄은 `#F1F5F9` 배경.
- 비활성 행은 흐리게 하되 "비활성" 글자를 같이 붙인다(투명도만으로 구분하지 않음).
- 표가 화면보다 넓으면 표를 감싼 상자에 가로 스크롤을 준다 [DB: Table Handling].

**상태 표시** [DB: Color Only — 색만으로 정보를 전달하지 않는다]
| 상태 | 글자 | 색 | 모양 |
|------|------|----|------|
| 부족 | "부족" | `#B91C1C` 글자 / `#FEF2F2` 배경 | 느낌표 원 SVG |
| 정상 | "정상" | `#15803D` 글자 / `#F0FDF4` 배경 | 체크 SVG |
| 판단 불가 | "판단 불가" + 사유 | `#475569` 글자 / `#F1F5F9` 배경 | 물음표 원 SVG |
색 값은 [기본값]이다. 셋 다 흰 배경 대비 4.5:1 이상. 배지에는 항상 글자가 들어간다.

**목업으로 정한 것** (2026-11-05, 발주 추천 2차 목업)
- 레이아웃: 왼쪽 사이드 메뉴(폭 220~240px, 흰 배경, 현재 메뉴는 `#EFF6FF` 배경 + `#1D4ED8` 글자) + 오른쪽 위 사용자 영역. 좁은 화면에서는 메뉴가 위로 쌓인다.
- 선택한 줄: 줄 전체 `#EFF6FF` 배경 + 첫 칸 왼쪽 3px `#2563EB` 세로줄.
- 열이 많은 표는 머리 위에 묶음 줄(예: 재고 / 판단 기준 / 추천)을 두고 묶음 사이에 세로 구분선을 넣는다.
- 판단에 쓰는 핵심 숫자만 굵게(추천 화면: 가용재고, 재주문점), 재료 숫자는 `--color-muted-foreground`로 낮춘다.
- 추천 화면 상태: 품절 위험 = 부족 배지(빨강), 발주 필요 = `#1D4ED8` 글자 / `#DBEAFE` 배경 + 시계 SVG.
- 긴 이유 문장: 칸에는 "가용 X ≤ 재주문점 Y" 요약, 누르면 전체 문장(`<details>`).

**아이콘**: 이모지를 아이콘으로 쓰지 않는다 [DB]. 라이브러리 없이 인라인 SVG로 몇 개만 둔다. 글자 옆 장식 아이콘은 `aria-hidden="true"`.

**차트** [DB: Trend Over Time]
- 시간 흐름은 꺾은선, 점이 4개 미만이면 숫자 카드로 대신한다.
- 여러 선은 색과 함께 실선/점선으로도 구분하고 선 끝에 이름을 직접 적는다. 같은 값을 표로도 보여준다.
- DB가 권한 Chart.js 등은 새 라이브러리라 쓰지 않는다. 필요해지면 따로 확인을 받는다.

---

## Global Rules

### Color Palette

| Role | Hex | CSS Variable |
|------|-----|--------------|
| Primary | `#2563EB` | `--color-primary` |
| On Primary | `#FFFFFF` | `--color-on-primary` |
| Secondary | `#3B82F6` | `--color-secondary` |
| On Secondary | `#000000` | `--color-on-secondary` |
| Accent/CTA | `#EA580C` | `--color-accent` |
| On Accent/CTA | `#000000` | `--color-on-accent` |
| Background | `#F8FAFC` | `--color-background` |
| Foreground | `#1E293B` | `--color-foreground` |
| Card | `#FFFFFF` | `--color-card` |
| Card Foreground | `#1E293B` | `--color-card-foreground` |
| Muted | `#E9EFF8` | `--color-muted` |
| Muted Foreground | `#475569` | `--color-muted-foreground` |
| Border | `#E2E8F0` | `--color-border` |
| Destructive | `#DC2626` | `--color-destructive` |
| On Destructive | `#FFFFFF` | `--color-on-destructive` |
| Ring | `#2563EB` | `--color-ring` |

**Color Notes:** Trust blue + orange CTA contrast [Accent adjusted from #F97316]

### Typography

- **Heading Font:** Plus Jakarta Sans
- **Body Font:** Plus Jakarta Sans
- **Mood:** friendly, modern, saas, clean, approachable, professional
- **Google Fonts:** [Plus Jakarta Sans + Plus Jakarta Sans](https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap)

**CSS Import:**
```css
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap');
```

### Spacing Variables

*Density: 7/10 — Standard*

| Token | Value | Usage |
|-------|-------|-------|
| `--space-xs` | `4px` / `0.25rem` | Tight gaps |
| `--space-sm` | `8px` / `0.5rem` | Icon gaps, inline spacing |
| `--space-md` | `16px` / `1rem` | Standard padding |
| `--space-lg` | `24px` / `1.5rem` | Section padding |
| `--space-xl` | `32px` / `2rem` | Large gaps |
| `--space-2xl` | `48px` / `3rem` | Section margins |
| `--space-3xl` | `64px` / `4rem` | Hero padding |

### Shadow Depths

| Level | Value | Usage |
|-------|-------|-------|
| `--shadow-sm` | `0 1px 2px rgba(0,0,0,0.05)` | Subtle lift |
| `--shadow-md` | `0 4px 6px rgba(0,0,0,0.1)` | Cards, buttons |
| `--shadow-lg` | `0 10px 15px rgba(0,0,0,0.1)` | Modals, dropdowns |
| `--shadow-xl` | `0 20px 25px rgba(0,0,0,0.15)` | Hero images, featured cards |

---

## Component Specs

### Buttons

```css
/* Primary Button */
.btn-primary {
  background: #EA580C;
  color: #000000;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}

.btn-primary:hover {
  opacity: 0.9;
  transform: translateY(-1px);
}

/* Secondary Button */
.btn-secondary {
  background: transparent;
  color: #2563EB;
  border: 2px solid #2563EB;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 600;
  transition: all 200ms ease;
  cursor: pointer;
}
```

### Cards

```css
.card {
  background: #F8FAFC;
  border-radius: 12px;
  padding: 24px;
  box-shadow: var(--shadow-md);
  transition: all 200ms ease;
  cursor: pointer;
}

.card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-2px);
}
```

### Inputs

```css
.input {
  padding: 12px 16px;
  border: 1px solid #E2E8F0;
  border-radius: 8px;
  font-size: 16px;
  transition: border-color 200ms ease;
}

.input:focus {
  border-color: #2563EB;
  outline: none;
  box-shadow: 0 0 0 3px #2563EB20;
}
```

### Modals

```css
.modal-overlay {
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
}

.modal {
  background: white;
  border-radius: 16px;
  padding: 32px;
  box-shadow: var(--shadow-xl);
  max-width: 500px;
  width: 90%;
}
```

---

## Style Guidelines

**Style:** Minimalism & Swiss Style

**Keywords:** Clean, simple, spacious, functional, white space, high contrast, geometric, sans-serif, grid-based, essential

**Best For:** Enterprise apps, dashboards, documentation sites, SaaS platforms, professional tools

**Key Effects:** Subtle hover (200-250ms), smooth transitions, sharp shadows if any, clear type hierarchy, fast loading

### Page Pattern

**Pattern Name:** Hero + Features + CTA

- **Conversion Strategy:** Deep CTA placement. For CTA label text, verify at least 4.5:1 against the button fill; use 7:1 only when the product explicitly targets AAA normal-text contrast. Keep focus and component boundaries independently visible. Disable hero parallax under reduced motion and render its static final state.
- **CTA Placement:** Hero (sticky) + Bottom
- **Section Order:** Hero with headline/image > Value prop > Key features (3-5) > CTA section > Footer

---

## Motion

**Scroll Reveal** (Subtle) — Trigger: scroll (viewport enter) | Duration: 300-400ms | Easing: `power1.out`

```js
gsap.from(el, { opacity: 0, y: 12, duration: 0.35, ease: 'power1.out', scrollTrigger: { trigger: el, start: 'top 90%', toggleActions: 'play none none reverse' } });
```

**Framework notes:** Requires the ScrollTrigger plugin registered once via gsap.registerPlugin(ScrollTrigger); Use matchMedia('(prefers-reduced-motion: reduce)') to skip non-essential motion and render the final state immediately

- ✅ Keep the y offset small (8-16px) so it reads as a fade, not a slide
- ❌ Don't reveal below-the-fold content needed for SEO/crawlers as invisible-by-default without a no-JS fallback
- ⚡ toggleActions 'play none none reverse' avoids re-triggering on every scroll direction change

---

## Anti-Patterns (Do NOT Use)

- ❌ Excessive animation
- ❌ Dark mode by default

### Additional Forbidden Patterns

- ❌ **Emojis as icons** — Use SVG icons (Heroicons, Lucide, Simple Icons)
- ❌ **Missing cursor:pointer** — All clickable elements must have cursor:pointer
- ❌ **Layout-shifting hovers** — Avoid scale transforms that shift layout
- ❌ **Low contrast text** — Maintain 4.5:1 minimum contrast ratio
- ❌ **Instant state changes** — Always use transitions (150-300ms)
- ❌ **Invisible focus states** — Focus states must be visible for a11y

---

## Pre-Delivery Checklist

Before delivering any UI code, verify:

- [ ] No emojis used as icons (use SVG instead)
- [ ] All icons from consistent icon set (Heroicons/Lucide)
- [ ] `cursor-pointer` on all clickable elements
- [ ] Hover states with smooth transitions (150-300ms)
- [ ] Light mode: text contrast 4.5:1 minimum
- [ ] Focus states visible for keyboard navigation
- [ ] `prefers-reduced-motion` respected
- [ ] Responsive: 375px, 768px, 1024px, 1440px
- [ ] No content hidden behind fixed navbars
- [ ] No horizontal scroll on mobile
