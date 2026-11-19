import type { Metadata } from "next"; // 제목·검색 노출 설정의 타입

// 공급업체 확인 화면(공개, (app) 그룹 밖): 제목과 검색 제외. 응답 헤더는 next.config.ts 의 /supplier-reply 규칙
export const metadata: Metadata = {
  title: "발주 확인",
  robots: { index: false, follow: false },
};

export default function SupplierReplyLayout({ children }: LayoutProps<"/supplier-reply">) {
  return <>{children}</>;
}
