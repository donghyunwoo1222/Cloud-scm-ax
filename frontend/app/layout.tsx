import type { Metadata } from "next"; // 페이지 제목·설명의 타입
import "./globals.css"; // 모든 화면에 적용할 기본 스타일

export const metadata: Metadata = {
  title: "Cloud SCM + AX", // 브라우저 탭에 보이는 제목
  description: "중소 유통업체용 재고·발주 관리", // 검색엔진 등에 보이는 설명
};

// 모든 화면을 감싸는 바깥 틀
export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko">
      {/* 문서 언어를 한국어로 표시 */}
      <body>{children}</body>
      {/* 각 화면(page.tsx)의 내용이 여기에 들어간다 */}
    </html>
  );
}
