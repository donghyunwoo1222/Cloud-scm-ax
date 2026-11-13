"use client"; // 폼을 다루는 화면이라 브라우저에서 실행

import { FormEvent, useEffect, useState } from "react"; // 폼 제출, 처음 한 번 불러오기, 상태

import { api } from "../../lib/api"; // 공통 API 호출 함수
import { Field } from "../../lib/field"; // 모바일에서 라벨이 테두리에 걸리는 입력 항목
import { ErrorText } from "../../lib/list"; // 오류 문장
import { useMe } from "../../lib/me"; // 내 정보(역할)
import { InfoTip } from "../../lib/tip"; // 보조 설명 말풍선
import { S } from "../../lib/styles"; // 화면 공통 스타일
import { useToast } from "../../lib/toast"; // 성공 알림 토스트

// GET /api/v1/company 응답 (회사는 로그인 토큰으로만 정해진다)
type Company = { name: string; business_number: string | null; representative: string | null; address: string | null; phone: string | null };

const FIELDS = ["business_number", "representative", "address", "phone"] as const; // 고칠 수 있는 칸
type Form = Record<(typeof FIELDS)[number], string>;
const LABELS = { business_number: "사업자등록번호", representative: "대표자", address: "주소", phone: "대표 연락처" };

// 저장된 숫자 10자리를 123-45-67890 모양으로 보여 준다
const show = (n: string | null) => (n && n.length === 10 ? `${n.slice(0, 3)}-${n.slice(3, 5)}-${n.slice(5)}` : n ?? "");

// 회사 정보 화면 (주소 /company): 관리자는 수정, 담당자는 읽기 전용
export default function CompanyPage() {
  const me = useMe();
  const [company, setCompany] = useState<Company | null>(null); // 서버에 저장된 값
  const [form, setForm] = useState<Form>({ business_number: "", representative: "", address: "", phone: "" }); // 입력값
  const [error, setError] = useState<unknown>(null); // 불러오기·저장 오류

  function fill(c: Company) {
    setCompany(c);
    setForm({ business_number: show(c.business_number), representative: c.representative ?? "", address: c.address ?? "", phone: c.phone ?? "" });
  }

  useEffect(() => {
    api<Company>("/company").then(fill).catch(setError);
  }, []);

  const toast = useToast(); // 성공 알림 토스트

  async function save(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    try {
      // 빈 칸은 null(비우기). 사업자번호 형식(숫자 10자리)은 서버가 검사한다
      const body = Object.fromEntries(FIELDS.map((f) => [f, form[f].trim() || null]));
      fill(await api<Company>("/company", { method: "PATCH", body }));
      setError(null);
      toast("회사 정보를 저장했어요");
    } catch (e) {
      setError(e);
    }
  }

  if (!me) return null; // 로그인 확인 전
  const isAdmin = me.role === "ADMIN";

  return (
    <section>
      <h1>회사 정보 <InfoTip label="회사 정보 설명" detail="발주서 문서의 머리말에 들어가는 우리 회사 정보입니다. 모두 비워 둬도 됩니다." /></h1>
      {!isAdmin && <p style={S.hint}>관리자만 고칠 수 있습니다.</p>}
      <ErrorText error={error} labels={LABELS} />
      {company && (
        <form className="form-compact field-form" onSubmit={save} style={{ ...S.sectionCard, ...S.formGrid }}>
          <Field label="회사명"><input value={company.name} readOnly disabled /></Field>
          <Field label={<>사업자등록번호 <InfoTip label="사업자등록번호 설명" detail="숫자 10자리. 123-45-67890처럼 하이픈을 넣어도 됩니다." /></>} short="사업자번호">
            <input inputMode="numeric" value={form.business_number} readOnly={!isAdmin} onChange={(e) => setForm({ ...form, business_number: e.target.value })} />
          </Field>
          <Field label="대표자"><input value={form.representative} readOnly={!isAdmin} onChange={(e) => setForm({ ...form, representative: e.target.value })} /></Field>
          <Field label="주소"><input value={form.address} readOnly={!isAdmin} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
          <Field label="대표 연락처"><input value={form.phone} readOnly={!isAdmin} onChange={(e) => setForm({ ...form, phone: e.target.value })} /></Field>
          {isAdmin && <div className="form-actions" style={S.buttons}><button type="submit">저장</button></div>}
        </form>
      )}
    </section>
  );
}
