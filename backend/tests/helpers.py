"""테스트 공통 도우미 (fixture 가 아닌 일반 값·함수)."""

PASSWORD = "test-password"  # conftest 의 world 사용자 공통 비밀번호 (테스트 전용)


def login_as(client, email: str = "staff@a.test") -> None:
    """이 이메일로 로그인해 클라이언트가 쿠키를 갖게 한다. 기본은 회사 A 담당자."""
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})  # 로그인 요청
    assert response.status_code == 200  # 실패하면 테스트 준비가 잘못된 것
