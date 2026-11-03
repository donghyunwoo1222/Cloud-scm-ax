from fastapi.testclient import TestClient  # 서버를 띄우지 않고 앱에 가짜 요청을 보내는 도구

from app.main import app  # 테스트할 앱

client = TestClient(app)  # 가짜 요청 보내는 클라이언트


def test_health_returns_ok():
    response = client.get("/api/v1/health")  # health 경로를 부른다
    assert response.status_code == 200  # 200(정상)이어야 한다
    assert response.json() == {"status": "ok"}  # 본문이 {"status": "ok"} 여야 한다
