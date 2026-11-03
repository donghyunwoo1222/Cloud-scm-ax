// 아직 만들지 않은 화면 자리 ("준비 중")
export default function ComingSoon({ title, issue }: { title: string; issue: string }) {
  return (
    <section>
      <h1>{title}</h1>
      {/* 화면 이름 */}
      <p>준비 중입니다. ({issue})</p>
      {/* 어느 이슈에서 만들지 */}
    </section>
  );
}
