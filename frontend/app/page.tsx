import { redirect } from "next/navigation"; // 다른 주소로 보내는 도구

// 첫 주소(/)는 대시보드로 보낸다. 로그인 안 했으면 대시보드 틀이 다시 로그인 화면으로 보낸다
export default function Home() {
  redirect("/dashboard");
}
