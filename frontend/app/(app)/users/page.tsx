"use client"; // 목록·폼을 다루는 화면이라 브라우저에서 실행

import { FormEvent, useState } from "react"; // 폼 제출, 상태

import { api } from "../../lib/api"; // 공통 API 호출 함수
import { ErrorText, ListControls, Pager, useList } from "../../lib/list"; // 목록 공통 부품
import { Me, ROLE_LABEL, useMe } from "../../lib/me"; // 내 정보·역할 한글 이름

// GET /api/v1/users 의 한 행 (비밀번호 해시는 서버가 아예 보내지 않는다)
type User = {
  id: number; // 번호
  name: string; // 이름
  email: string; // 이메일 (로그인 ID)
  role: Me["role"]; // ADMIN / STAFF
  is_active: boolean; // 활성 여부
};

const EMPTY = { name: "", email: "", password: "", role: "" }; // 생성 폼 빈 값 (역할은 직접 고르게 한다)
type Form = typeof EMPTY;
const LABELS = { name: "이름", email: "이메일", password: "임시 비밀번호", role: "역할" }; // 오류 칸 이름 → 화면 이름

// 사용자 관리 화면 (주소 /users)
export default function UsersPage() {
  const me = useMe(); // 내 정보
  if (!me) return null; // 로그인 확인 전 (레이아웃이 숨겨 둔 상태)
  // 담당자가 주소를 직접 쳐서 들어온 경우 안내만 한다. 실제 차단은 서버(/api/v1/users 가 403)가 한다
  if (me.role !== "ADMIN") return <p role="alert">관리자만 볼 수 있는 화면입니다.</p>;
  return <UsersAdmin me={me} />;
}

// 관리자에게만 보이는 본문: 직원 목록 + 계정 생성 + 역할 변경·비활성
function UsersAdmin({ me }: { me: Me }) {
  const list = useList<User>("/users"); // 목록 상태 (20개씩, 최신순, 비활성 포함 보기. 이 API 는 검색어가 없다)
  const [form, setForm] = useState<Form>(EMPTY); // 생성 폼 입력값
  const [error, setError] = useState<unknown>(null); // 저장·변경 오류

  function set(field: keyof Form, value: string) {
    setForm({ ...form, [field]: value }); // 한 칸만 바꾼다
  }

  async function create(event: FormEvent) {
    event.preventDefault(); // 새로고침 막기
    try {
      // 비밀번호 8자 규칙·이메일 중복은 서버가 검사한다 (화면은 message 를 보여준다)
      await api("/users", { method: "POST", body: { ...form, role: form.role || null } });
      setForm(EMPTY); // 성공하면 폼을 비운다. 임시 비밀번호는 다시 보여주지 않는다 (관리자가 직접 전달)
      setError(null);
      await list.reload(); // 목록 다시 불러오기
    } catch (e) {
      setError(e); // 예: "이미 사용 중인 이메일입니다."
    }
  }

  // 한 사람의 역할·활성 여부 바꾸기. 바뀐 칸 하나만 보낸다 (예: {"role": "STAFF"})
  async function update(user: User, change: Partial<Pick<User, "role" | "is_active">>) {
    try {
      await api(`/users/${user.id}`, { method: "PATCH", body: change });
      setError(null);
      if (user.email === me.email) {
        // 내 계정을 바꿨으면 메뉴·권한이 달라지므로 화면 전체를 새로 연다 (담당자가 됐으면 이 화면은 안내 문장으로 바뀐다)
        window.location.reload();
        return;
      }
      await list.reload();
    } catch (e) {
      setError(e); // 예: "회사에는 활성 관리자가 최소 1명 있어야 합니다."
      await list.reload(); // 거절됐으면 선택 상자를 원래 값으로 되돌린다
    }
  }

  return (
    <section>
      <h1>사용자 관리</h1>

      <form onSubmit={create} style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))", gap: "0.5rem", alignItems: "end", margin: "1rem 0" }}>
        {/* 계정 생성 폼 */}
        <label>이름* <input value={form.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label>이메일* <input type="email" value={form.email} onChange={(e) => set("email", e.target.value)} autoComplete="off" /></label>
        <label>
          임시 비밀번호*
          <input type="password" value={form.password} onChange={(e) => set("password", e.target.value)} autoComplete="new-password" />
          {/* 화면에 글자를 보이지 않게, 브라우저가 내 비밀번호를 자동으로 채우지 않게 */}
        </label>
        <label>
          역할*
          <select value={form.role} onChange={(e) => set("role", e.target.value)} style={{ display: "block" }}>
            <option value="">선택하세요</option>
            <option value="STAFF">담당자</option>
            <option value="ADMIN">관리자</option>
          </select>
        </label>
        <div><button type="submit">계정 만들기</button></div>
      </form>
      <ErrorText error={error} labels={LABELS} />

      <ListControls includeInactive={list.includeInactive} onToggleInactive={list.toggleInactive} />
      {/* 검색창 없이 "비활성 포함"만 */}
      <ErrorText error={list.error} />
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ textAlign: "left" }}>
            <th>이름</th><th>이메일</th><th>역할</th><th>상태</th><th></th>
          </tr>
        </thead>
        <tbody>
          {list.rows.map((u) => (
            <tr key={u.id} style={{ borderTop: "1px solid #ccc", opacity: u.is_active ? 1 : 0.5 }}>
              {/* 비활성 행은 흐리게 */}
              <td>{u.name}{u.email === me.email && " (나)"}</td>
              {/* 내 계정 표시 (이메일은 전체에서 하나뿐이라 이걸로 알아본다) */}
              <td>{u.email}</td>
              <td>
                <select value={u.role} onChange={(e) => update(u, { role: e.target.value as User["role"] })} aria-label={`${u.name} 역할`}>
                  {/* 바꾸면 바로 저장. 마지막 관리자면 서버가 막고 원래 값으로 돌아간다 */}
                  <option value="ADMIN">{ROLE_LABEL.ADMIN}</option>
                  <option value="STAFF">{ROLE_LABEL.STAFF}</option>
                </select>
              </td>
              <td>{u.is_active ? "활성" : "비활성"}</td>
              <td>
                {u.is_active
                  ? <button type="button" onClick={() => update(u, { is_active: false })}>비활성</button>
                  : <button type="button" onClick={() => update(u, { is_active: true })}>다시 활성</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager meta={list.meta} onPage={list.setPage} />
    </section>
  );
}
