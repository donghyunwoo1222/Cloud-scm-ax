"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import Link from "next/link"; // 공급업체 상세 화면 링크
import { FormEvent, useEffect, useRef, useState } from "react"; // 폼 제출, 처음 한 번 실행(?edit= 읽기), 상태

import { api } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { StatusBadge } from "../../lib/status-badge"; // 색 + 글자 + 아이콘 상태 배지
import { S, bodyRow } from "../../lib/styles"; // 화면 공통 스타일

// GET /api/v1/suppliers 의 한 행
type Supplier = {
  id: number; // 번호
  name: string; // 업체명
  lead_time_days: number; // 리드타임(일)
  contact_name: string | null; // 담당자
  phone: string | null; // 연락처
  email: string | null; // 이메일
  memo: string | null; // 메모
  is_active: boolean; // 활성 여부
};

// 폼 입력값 (입력칸은 모두 글자로 다루고 보낼 때 바꾼다)
const EMPTY = { name: "", lead_time_days: "", contact_name: "", phone: "", email: "", memo: "" };
type Form = typeof EMPTY;

// 오류 details 의 칸 이름 → 화면 이름
const LABELS = { name: "업체명", lead_time_days: "리드타임", contact_name: "담당자", phone: "연락처", email: "이메일", memo: "메모" };

// 폼 값 → 서버로 보낼 본문. 빈 선택 칸은 null(비우기), 리드타임은 숫자로 (검사는 서버가 한다: 음수·소수는 422)
function toBody(form: Form) {
  return {
    name: form.name, // 업체명 (앞뒤 공백은 서버가 지운다)
    lead_time_days: form.lead_time_days === "" ? null : Number(form.lead_time_days), // "5" → 5, 비우면 null(→ 서버가 422)
    contact_name: form.contact_name || null,
    phone: form.phone || null,
    email: form.email || null,
    memo: form.memo || null,
  };
}

// 공급업체 화면 (주소 /suppliers): 목록 + 등록·수정 폼 (수정·비활성은 업체 상세 화면에서 시작한다)
export default function SuppliersPage() {
  const list = useList<Supplier>("/suppliers"); // 목록 상태 (20개씩, 최신순, 검색, 비활성 포함)
  const [form, setForm] = useState<Form>(EMPTY); // 폼 입력값
  const [editingId, setEditingId] = useState<number | null>(null); // 수정 중인 업체 번호 (null 이면 새 등록)
  const registration = useRef<HTMLDetailsElement>(null); // 목록에서 수정할 때 폼을 펼친다.
  const [created, setCreated] = useState(false);
  const [error, setError] = useState<unknown>(null); // 저장·버튼 오류

  function set(field: keyof Form, value: string) {
    setForm({ ...form, [field]: value }); // 한 칸만 바꾼다
  }

  // 상세 화면의 "수정"은 /suppliers?edit=번호 로 온다: 그 업체를 불러와 수정 폼을 연다 (목록 표에는 수정 버튼을 두지 않는다)
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("edit");
    if (!id) return;
    window.history.replaceState(null, "", "/suppliers"); // 저장 후 새로고침해도 폼이 다시 열리지 않게 주소에서 지운다
    api<Supplier>(`/suppliers/${id}`).then((s) => {
      if (registration.current) registration.current.open = true;
      registration.current?.querySelector("input")?.focus();
      setEditingId(s.id); // 수정 모드
      setForm({
        name: s.name, lead_time_days: String(s.lead_time_days), contact_name: s.contact_name ?? "",
        phone: s.phone ?? "", email: s.email ?? "", memo: s.memo ?? "",
      }); // 그 업체 값으로 폼 채우기
    }).catch(setError);
  }, []);

  function reset() {
    setEditingId(null); // 새 등록 모드로
    setForm(EMPTY); // 폼 비우기
  }

  async function save(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    try {
      if (editingId === null) await api("/suppliers", { method: "POST", body: toBody(form) }); // 등록
      else await api(`/suppliers/${editingId}`, { method: "PATCH", body: toBody(form) }); // 수정
      setCreated(editingId === null);
      reset(); // 성공하면 폼 비우기
      if (registration.current) registration.current.open = false;
      setError(null);
      await list.reload(); // 목록 다시 불러오기
    } catch (e) {
      setError(e); // 서버 message 그대로 보여준다 (예: 업체명 중복)
    }
  }

  return (
    <section>
      <h1>공급업체</h1>

      {created && <p role="status" style={S.ok}>공급업체를 등록했습니다. <Link href="/products">품목 등록으로 이동</Link></p>}
      <details ref={registration} style={S.sectionCard}>
      <summary>{editingId === null ? "공급업체 등록" : "공급업체 수정"}</summary>
      <form onSubmit={save} style={S.formGrid}>
        {/* 등록·수정 폼: 칸을 가로로 나열 */}
        <label>업체명* <input value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>입고 소요일(일)* <input type="number" inputMode="numeric" value={form.lead_time_days} onChange={(e) => set("lead_time_days", e.target.value)} />
          <small>발주 후 입고까지 걸리는 기간(리드타임)</small>
        </label>
        {/* 음수·소수 검사는 서버가 한다 (화면은 서버 message 를 보여준다) */}
        <label>담당자 <input value={form.contact_name} onChange={(e) => set("contact_name", e.target.value)} /></label>
        <label>연락처 <input value={form.phone} onChange={(e) => set("phone", e.target.value)} /></label>
        <label>이메일 <input value={form.email} onChange={(e) => set("email", e.target.value)} /></label>
        <label>메모 <input value={form.memo} onChange={(e) => set("memo", e.target.value)} /></label>
        <div style={S.buttons}>
          <button type="submit">{editingId === null ? "등록" : "수정 저장"}</button>
          {editingId !== null && <button type="button" onClick={reset}>취소</button>}
          {/* 수정 중일 때만 취소 */}
        </div>
      </form>
      </details>
      <ErrorText error={error} labels={LABELS} />

      <ListControls placeholder="업체명 검색" includeInactive={list.includeInactive} onSearch={list.search} onToggleInactive={list.toggleInactive} />
      <ErrorText error={list.error} />
      <div style={S.tableBox}>
      <table style={S.table}>
        <thead>
          <tr style={S.headRow}>
            <th>업체명</th><th style={S.num}>입고 소요일</th><th>담당자</th><th>연락처</th><th>상태</th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((s) => (
            <tr key={s.id} style={bodyRow(s.is_active)}>
              {/* 비활성 행은 흐리게 */}
              <td><Link href={`/suppliers/${s.id}`}>{s.name}</Link></td>
              <td style={S.num}>{s.lead_time_days}일</td>
              <td>{s.contact_name ?? "-"}</td>
              <td style={S.nowrap}>{s.phone ?? "-"}</td>
              <td style={S.nowrap}>{s.is_active ? <StatusBadge kind="ok">활성</StatusBadge> : <StatusBadge kind="unknown">비활성</StatusBadge>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {list.meta?.total === 0 && <p style={S.empty}>{list.includeInactive ? "공급업체가 없습니다." : "활성 공급업체가 없습니다."}</p>}
      {/* 빈 목록 안내 */}
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
