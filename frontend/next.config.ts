import type { NextConfig } from "next"; // Next.js 설정의 타입(모양) 정의

// 백엔드(FastAPI) 주소. 환경 변수가 없으면 로컬 Docker 백엔드(8001)를 쓴다
const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8001";

const nextConfig: NextConfig = {
  cacheComponents: true, // create-next-app 기본값 그대로 둔다
  partialPrefetching: true, // create-next-app 기본값 그대로 둔다
  async rewrites() {
    // 브라우저가 보낸 /api/* 요청을 백엔드로 그대로 전달한다 (브라우저 입장에선 같은 주소라 CORS가 필요 없다)
    return [{ source: "/api/:path*", destination: `${backendUrl}/api/:path*` }];
  },
  async headers() {
    // 공급업체 확인 화면(#265, 로그인 없음): 주소 # 뒤 토큰이 다른 사이트로 새거나(Referer) 검색·캐시에 남지 않게
    const supplierReply = [
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "X-Robots-Tag", value: "noindex" },
      { key: "Cache-Control", value: "no-store" },
    ];
    return [
      { source: "/supplier-reply", headers: supplierReply },
      { source: "/supplier-reply/:path*", headers: supplierReply },
    ];
  },
};

export default nextConfig; // 이 설정을 Next.js가 읽는다
