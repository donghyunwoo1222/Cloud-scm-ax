// 화면 기능 스위치. NEXT_PUBLIC_ 변수는 빌드할 때 값이 박힌다(바꾸려면 다시 빌드).
// 외화(해외) 발주 화면: 기본은 꺼짐. 켜려면 빌드 환경에 NEXT_PUBLIC_FX_ENABLED=true (#267, 국내 배포를 먼저 한다)
export const FX_ENABLED = process.env.NEXT_PUBLIC_FX_ENABLED === "true";
