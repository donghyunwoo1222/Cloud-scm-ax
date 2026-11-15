"""슬랙 연결 코드 테스트 (#197). 슬랙은 호출하지 않는다: 웹 API(발급·상태·해제)와 redeem_code 서비스만 검증한다."""

import logging  # 감사 로그 확인
from datetime import UTC, datetime, timedelta  # 고정 시각, 시간 이동

import pytest  # 테스트 도구
from sqlalchemy import select  # 행 조회

from app.config import settings  # SLACK_* 설정
from app.models import SlackLink, User  # 슬랙 연결 표, 사용자 표
from app.services import slack_link  # 검사 대상
from tests.concurrency import (  # 동시 요청 도구
    delayed,
    hold_row_lock,
    run_at_once,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인

T0 = datetime(2026, 11, 16, 0, 0, tzinfo=UTC)  # 고정 시각 (서울 11-16 09:00)
TEAM = "T0TEAM"  # 허용 워크스페이스


@pytest.fixture(autouse=True)
def clean_failures():
    slack_link.reset()  # 테스트끼리 실패 기록이 섞이지 않게
    yield


@pytest.fixture
def slack_on(monkeypatch):
    monkeypatch.setattr(settings, "slack_enabled", True)
    monkeypatch.setattr(settings, "slack_team_id", TEAM)
    monkeypatch.setattr("app.services.slack_link.now", lambda: T0)


@pytest.fixture
def logs(caplog, monkeypatch):
    monkeypatch.setattr(slack_link.log, "disabled", False)  # 같은 실행의 DB 준비(alembic fileConfig)가 이미 만든 로거를 꺼 두기 때문 (test_llm 과 같다)
    caplog.set_level(logging.INFO, logger="app.services.slack_link")
    return caplog


@pytest.fixture
def reasons(logs):
    """감사 로그의 outcome 값 목록을 돌려주는 함수."""
    caplog = logs
    return lambda: [r.args[1] for r in caplog.records if r.name == "app.services.slack_link"]


def issue(client, email="staff@a.test") -> str:
    login_as(client, email)
    response = client.post("/api/v1/slack/link/code")
    assert response.status_code == 201
    return response.json()["data"]["code"]


def redeem(session, code, user="U1", at=T0, team=TEAM):
    return slack_link.redeem_code(session, team, user, code, at)


# ----- 스위치 -----

def test_disabled_blocks_issue_but_allows_status_and_unlink(client, world):
    login_as(client)
    assert client.post("/api/v1/slack/link/code").status_code == 503  # 기본값: 꺼짐
    assert client.get("/api/v1/slack/link").json()["data"] == {
        "enabled": False, "status": "NONE", "code_expires_at": None, "slack_user_id": None, "linked_at": None}
    assert client.post("/api/v1/slack/link/unlink").status_code == 200  # 해제는 꺼져 있어도 된다


def test_team_id_required(client, world, monkeypatch):
    monkeypatch.setattr(settings, "slack_enabled", True)  # 스위치만 켜고 워크스페이스는 비움
    login_as(client)
    assert client.post("/api/v1/slack/link/code").json()["error"]["code"] == "SLACK_DISABLED"


def test_login_required(client, world, slack_on):
    assert client.get("/api/v1/slack/link").status_code == 401
    assert client.post("/api/v1/slack/link/code").status_code == 401


# ----- 발급 -----

def test_issue_stores_only_hash(client, world, session, slack_on):
    code = issue(client)
    assert len(code) == 6 and code.isdigit()
    row = session.scalar(select(SlackLink).where(SlackLink.user_id == world["a_staff"].id))
    assert row.company_id == world["a_company"].id  # 회사는 토큰에서
    assert row.link_code_hash == slack_link.hash_code(code) and code not in row.link_code_hash  # 원문은 어디에도 없다
    assert row.link_code_expires_at == T0 + timedelta(minutes=10)
    body = client.get("/api/v1/slack/link").json()["data"]
    assert body["status"] == "PENDING" and body["enabled"] is True


def test_reissue_invalidates_old_code(client, world, session, slack_on):
    old = issue(client)
    new = issue(client)
    if old == new:  # 100만분의 1: 같은 숫자가 다시 나오면 이 테스트는 의미가 없다
        pytest.skip("같은 코드가 다시 나왔다")
    assert redeem(session, old) is None
    assert redeem(session, new, user="U2") is not None


def test_code_collision_draws_again(client, world, session, slack_on, monkeypatch):
    first = issue(client, "staff@a.test")
    draws = iter([int(first), 123456 if first != "123456" else 654321])  # 첫 번째는 이미 살아 있는 코드와 같다
    monkeypatch.setattr("app.services.slack_link.secrets.randbelow", lambda _: next(draws))
    second = issue(client, "admin@b.test")
    assert second != first


def test_issue_when_linked_is_409(client, world, session, slack_on):
    assert redeem(session, issue(client)) is not None
    assert client.post("/api/v1/slack/link/code").json()["error"]["code"] == "SLACK_ALREADY_LINKED"


# ----- 사용 -----

def test_redeem_links_to_code_owner(client, world, session, slack_on, reasons):
    code = issue(client, "admin@b.test")  # B회사 관리자의 코드
    row = redeem(session, code)
    assert (row.company_id, row.user_id) == (world["b_company"].id, world["b_admin"].id)  # 회사는 코드 주인 행에서
    assert row.link_code_hash is None and row.link_code_expires_at is None  # 한 번 쓰면 폐기
    body = client.get("/api/v1/slack/link").json()["data"]
    assert body["status"] == "LINKED" and body["slack_user_id"] == "U1"
    assert reasons()[-1] == "OK"


def test_used_code_fails(client, world, session, slack_on, reasons):
    code = issue(client)
    assert redeem(session, code) is not None
    assert redeem(session, code, user="U2") is None
    assert reasons()[-1] == "NOT_FOUND"  # 해시를 비웠으므로 다 쓴 코드는 "없음"


def test_expired_code_fails(client, world, session, slack_on, reasons):
    code = issue(client)
    assert redeem(session, code, at=T0 + timedelta(minutes=10)) is None  # 정확히 10분 뒤
    assert reasons()[-1] == "EXPIRED"


def test_wrong_team_fails(client, world, session, slack_on, reasons):
    code = issue(client)
    assert redeem(session, code, team="T0OTHER") is None
    assert reasons()[-1] == "WRONG_TEAM"
    assert redeem(session, code) is not None  # 코드는 그대로 살아 있다


def test_slack_user_already_linked_fails(client, world, session, slack_on, reasons):
    assert redeem(session, issue(client, "staff@a.test")) is not None  # U1 → A 담당자
    assert redeem(session, issue(client, "admin@a.test")) is None  # U1 을 다른 사람에게 또 연결
    assert reasons()[-1] == "ALREADY_LINKED"


def test_lock_after_five_failures(client, world, session, slack_on, reasons):
    code = issue(client)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert redeem(session, wrong) is None
    assert redeem(session, code) is None  # 6번째는 맞는 코드여도 막힌다
    assert reasons()[-1] == "LOCKED"
    assert redeem(session, code, user="U2") is not None  # 다른 슬랙 사용자는 막히지 않는다


def test_lock_releases_after_15_minutes(client, world, session, slack_on, monkeypatch):
    for _ in range(5):
        redeem(session, "abc")  # 모양이 틀린 입력도 실패로 센다
    monkeypatch.setattr("app.services.slack_link.now", lambda: T0 + timedelta(minutes=15))
    code = issue(client)  # 15분 뒤에 새 코드
    assert redeem(session, code, at=T0 + timedelta(minutes=15)) is not None


def test_log_has_no_code(client, world, session, slack_on, logs):
    code = issue(client)
    redeem(session, code)
    text = logs.text
    assert "outcome=OK" in text  # 로그가 실제로 잡혔는지 먼저 확인
    assert code not in text and slack_link.hash_code(code) not in text and "U1" not in text


# ----- 회사 분리·해제 -----

def test_status_and_unlink_touch_only_own_row(client, world, session, slack_on):
    assert redeem(session, issue(client, "admin@b.test")) is not None  # B 관리자 연결
    login_as(client, "staff@a.test")
    assert client.get("/api/v1/slack/link").json()["data"]["status"] == "NONE"  # A 담당자는 남의 연결을 못 본다
    client.post("/api/v1/slack/link/unlink")
    assert session.scalar(select(SlackLink).where(SlackLink.user_id == world["b_admin"].id)) is not None  # B 연결은 그대로
    login_as(client, "admin@b.test")
    assert client.post("/api/v1/slack/link/unlink").json()["data"]["status"] == "NONE"
    assert session.scalar(select(SlackLink).where(SlackLink.user_id == world["b_admin"].id)) is None


# ----- 동시성 -----

def test_same_code_twice_at_once_links_once(engine, committed_company, slack_on):
    """같은 코드를 두 슬랙 사용자가 동시에 내면 정확히 한 번만 성공한다(코드 행 잠금 → 뒤 요청은 비워진 해시를 못 찾는다)."""
    admin_id = committed_company["admin_id"]
    code, _ = run_in_new_session(engine, lambda s: slack_link.issue_code(s, s.get(User, admin_id), T0))
    link_id = run_in_new_session(engine, lambda s: s.scalar(select(SlackLink.id).where(SlackLink.user_id == admin_id)))
    results = run_at_once(
        hold_row_lock(engine, SlackLink, link_id),  # 문지기: 두 요청이 모두 잠금 앞에 도착하게
        delayed(lambda: run_in_new_session(engine, lambda s: redeem(s, code, user="U1"))),
        delayed(lambda: run_in_new_session(engine, lambda s: redeem(s, code, user="U2"))),
    )[1:]
    assert not any(isinstance(r, Exception) for r in results), results
    assert sum(r is not None for r in results) == 1
