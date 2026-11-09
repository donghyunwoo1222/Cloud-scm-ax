"use client"; // 인쇄 버튼과 불러오기를 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 발주서 상세로 돌아가기
import { useParams } from "next/navigation"; // 주소의 [id]
import { Suspense, useEffect, useState } from "react"; // 처음 한 번 불러오기, 상태, 주소 번호를 기다릴 자리

import { api } from "../../../../lib/api"; // 공통 API 호출 함수
import { ErrorText } from "../../../../lib/list"; // 오류 문장
import { S } from "../../../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/purchase-orders/{id}/document 응답. 금액·한글 금액·납품장소 대체는 모두 서버가 계산한다(엑셀과 같은 값).
type Doc = {
  po_number: string; order_date: string;
  supplier: { name: string; contact_name: string | null; phone: string | null; email: string | null };
  buyer: { name: string; business_number: string | null; representative: string | null; phone: string | null; address: string | null; author_name: string };
  lines: { no: number; product_name: string; product_sku: string; unit: string; quantity: number; unit_price: number; amount: number; note: string }[];
  supply_total: number; vat: number; total: number; total_korean: string;
  due_date: string | null; delivery_address: string | null; payment_terms: string | null; memo: string | null;
};

const won = (n: number) => n.toLocaleString("ko-KR"); // 836000 → 836,000
const bizNo = (n: string | null) => (n && n.length === 10 ? `${n.slice(0, 3)}-${n.slice(3, 5)}-${n.slice(5)}` : n ?? ""); // 1234567890 → 123-45-67890
const MIN_ROWS = 5; // 목업처럼 빈 줄을 채워 양식 모양을 유지한다

function Document() {
  const { id } = useParams<{ id: string }>(); // 주소의 발주서 번호
  const [doc, setDoc] = useState<Doc | null>(null); // 문서 값
  const [error, setError] = useState<unknown>(null); // 불러오기 오류 (승인 전 409, 다른 회사 404)

  useEffect(() => {
    api<Doc>(`/purchase-orders/${id}/document`).then(setDoc).catch(setError);
  }, [id]);

  if (!doc) return <section><h1>발주서 문서</h1><ErrorText error={error} /><Link href={`/purchase-orders/${id}`}>발주서 상세로</Link></section>;

  const blanks = Array.from({ length: Math.max(0, MIN_ROWS - doc.lines.length) }, (_, i) => doc.lines.length + i + 1); // 빈 줄 번호
  const { supplier: s, buyer: b } = doc;

  return (
    <section>
      <div className="no-print" style={{ ...S.buttons, marginBottom: "var(--space-md)" }}>
        <Link href={`/purchase-orders/${id}`} style={S.linkButtonGhost}>발주서 상세로</Link>
        <button type="button" className="primary-action" onClick={() => window.print()}>인쇄 · PDF 저장</button>
        {/* 엑셀은 같은 주소의 GET 이라 링크 하나로 내려받는다 (로그인 쿠키가 자동으로 붙는다) */}
        <a href={`/api/v1/purchase-orders/${id}/document.xlsx`} download style={S.linkButtonGhost}>엑셀</a>
      </div>

      <div className="po-paper">
        <div className="po-scroll">
          <h2>발 주 서</h2>
          <table>
            <colgroup><col style={{ width: 72 }} /><col /><col style={{ width: 150 }} /><col style={{ width: 82 }} /><col /></colgroup>
            <tbody>
              <tr>
                <th colSpan={2}>수신처</th>
                <td rowSpan={4} className="c" style={{ lineHeight: 1.9 }}>발주번호<br /><b style={{ fontWeight: 500 }}>{doc.po_number}</b><br />발주일자<br />{doc.order_date}</td>
                <th colSpan={2}>발주처</th>
              </tr>
              <tr><td className="lb">상 호</td><td>{s.name}</td><td className="lb">상 호</td><td>{b.name}</td></tr>
              <tr><td className="lb">담당자</td><td>{s.contact_name}</td><td className="lb">사업자번호</td><td>{bizNo(b.business_number)}</td></tr>
              <tr><td className="lb">연락처</td><td>{s.phone}</td><td className="lb">대표자</td><td>{b.representative}</td></tr>
              <tr>
                <td className="lb">이메일</td><td>{s.email}</td>
                <td className="c" style={{ fontSize: 11, color: "#666" }}>공급업체 정보</td>
                <td className="lb">담당자</td><td>{b.author_name} <span style={{ color: "#666" }}>(작성자)</span></td>
              </tr>
              <tr><td colSpan={3} style={{ borderTop: 0, borderRight: 0, borderBottom: 0 }} /><td className="lb">연락처</td><td>{b.phone}</td></tr>
              <tr><td colSpan={2} className="lb">주 소</td><td colSpan={3}>{b.address}</td></tr>
            </tbody>
          </table>

          <div className="total-box">합계금액 : 일금 <b style={{ fontWeight: 500 }}>{doc.total_korean}</b> 원정 (₩{won(doc.total)}), 부가세 포함</div>

          <table style={{ borderTop: 0 }}>
            <colgroup><col style={{ width: 34 }} /><col /><col style={{ width: 46 }} /><col style={{ width: 58 }} /><col style={{ width: 76 }} /><col style={{ width: 92 }} /><col style={{ width: 100 }} /></colgroup>
            <tbody>
              <tr><th>No.</th><th>품목명 (SKU)</th><th>단위</th><th>수량</th><th>단가</th><th>공급가액</th><th>비고</th></tr>
              {doc.lines.map((l) => (
                <tr key={l.no}>
                  <td className="c">{l.no}</td><td>{l.product_name} ({l.product_sku})</td><td className="c">{l.unit}</td>
                  <td className="r">{won(l.quantity)}</td><td className="r">{won(l.unit_price)}</td><td className="r">{won(l.amount)}</td>
                  <td style={{ fontSize: 11 }}>{l.note}</td>
                </tr>
              ))}
              {blanks.map((n) => <tr key={n}><td className="c">{n}</td><td /><td /><td /><td /><td /><td /></tr>)}
              <tr><th colSpan={5}>공급가액 합계</th><td className="r" colSpan={2}>{won(doc.supply_total)}</td></tr>
              <tr><th colSpan={5}>부가세 (10%)</th><td className="r" colSpan={2}>{won(doc.vat)}</td></tr>
              <tr><th colSpan={5}>합계</th><td className="r" colSpan={2}><b style={{ fontWeight: 500 }}>{won(doc.total)}</b></td></tr>
            </tbody>
          </table>

          <table style={{ borderTop: 0 }}>
            <tbody>
              <tr><td className="lb" rowSpan={4}>발주<br />조건</td><td>1) 납기일자 : {doc.due_date ?? ""}</td></tr>
              <tr><td>2) 납품장소 : {doc.delivery_address ?? ""}</td></tr>
              <tr><td>3) 지불조건 : {doc.payment_terms ?? ""}</td></tr>
              <tr><td>4) 기타 : {doc.memo ?? ""}</td></tr>
            </tbody>
          </table>
          <p className="c" style={{ margin: "14px 0 0" }}>위와 같이 발주합니다.</p>
        </div>
      </div>
    </section>
  );
}

// 주소의 번호는 화면이 열릴 때 알 수 있어 Suspense 로 감싼다 (빌드 때 미리 그리는 동안 기다릴 자리)
export default function Page() {
  return (
    <Suspense fallback={<p>불러오는 중…</p>}>
      <Document />
    </Suspense>
  );
}
