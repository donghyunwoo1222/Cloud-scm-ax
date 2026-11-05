import type { Metadata } from "next"; // 페이지 제목·설명의 타입
import { Noto_Sans_KR } from "next/font/google"; // Next.js 내장 폰트 도구 (빌드 때 내려받아 우리 서버에서 준다, 새 라이브러리 아님)
import "./globals.css"; // 모든 화면에 적용할 기본 스타일

// 한글 폰트. 한글 글자 조각은 subsets 에 없어 미리 불러오기(preload)를 끄고, 화면에 나온 글자 조각만 받는다
const notoSansKr = Noto_Sans_KR({
  weight: ["400", "500", "700"], // 본문·강조·제목
  preload: false,
  display: "swap", // 폰트가 오기 전에는 기본 폰트로 먼저 보여 준다
  variable: "--font-noto-sans-kr", // globals.css 의 --font-sans 가 이 이름을 쓴다
});

export const metadata: Metadata = {
  title: "Cloud SCM + AX", // 브라우저 탭에 보이는 제목
  description: "중소 유통업체용 재고·발주 관리", // 검색엔진 등에 보이는 설명
};

// 모든 화면을 감싸는 바깥 틀
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={notoSansKr.variable}>
      {/* 문서 언어를 한국어로 표시 */}
      <body>{children}</body>
      {/* 각 화면(page.tsx)의 내용이 여기에 들어간다 */}
    </html>
  );
}
