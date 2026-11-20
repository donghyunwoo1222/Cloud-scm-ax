"""메일 발송 시도 이력 po_email_log (#182): 성공·실패·저장 실패(UNSAVED) 기록, 토큰·원문 비저장, 조회 API, 회사 분리, 동시 발송.

메일은 가짜 서버(monkeypatch), 서버 실행 없음. 토큰 원본 값은 테스트 안에서만 쓰고 출력하지 않는다.
"""

import logging  # 로그 캡처
import smtplib  # 실패 흉내

import pytest  # 테스트 도구
from sqlalchemy import select  # 조회

from app.api import purchase_orders as po_api  # 이력 저장 실패 로그를 내는 경로 파일
from app.auth.security import hash_reset_token  # 저장되면 안 되는 토큰 해시
from app.config import settings  # SMTP·링크 설정 (테스트 동안만 바꾼다)
from app.main import app  # 등록된 경로 목록
from app.models import PoChangeLog, PoEmailLog, PurchaseOrder, Supplier, User  # 확인할 표
from app.services import po_mail  # 대상
from tests.concurrency import delayed, hold_row_lock, ordered_po, run_at_once, run_in_new_session
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_document import make_order  # 승인된 발주서
from tests.test_supplier_reply import TOKEN_RE  # 메일 본문의 링크 토큰 모양

URL = "/api/v1/purchase-orders"
RAW = "RAW-SMTP-MESSAGE-182"  # 메일 서버 원문 표식: 이력 어디에도 남으면 안 된다
OUT_KEYS = {"id", "kind", "to_address", "sent_by_name", "result", "failure_code", "with_link", "created_at"}


@pytest.fixture
def outbox(monkeypatch):
    """가짜 메일 서버 + 확인 링크 켜짐(https). 보낸 메일은 목록에 담긴다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(settings, "app_base_url", "https://scm.test")
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    monkeypatch.setattr(po_mail, "deliver", sent.append)
    return sent


def approved(client, session, world, email="sales@a-supplier.test"):
    world["a_supplier"].email = email
    session.commit()
    order, _ = make_order(client, session, world)
    return order


def send(client, order, resend=False):
    return client.post(f"{URL}/{order['id']}/email", json={"intro": "안녕하세요.", "resend": resend})


def rows(session, order_id) -> list[PoEmailLog]:
    session.expire_all()
    return list(session.scalars(select(PoEmailLog).where(PoEmailLog.purchase_order_id == order_id).order_by(PoEmailLog.id)))


def po(session, order_id) -> PurchaseOrder:
    session.expire_all()
    return session.get(PurchaseOrder, order_id)


def all_values(session, order_id) -> str:
    """이력 행들의 모든 칸 값을 글자 하나로 (비저장 검사용)."""
    return "\n".join(str(getattr(r, c.name)) for r in rows(session, order_id) for c in PoEmailLog.__table__.columns)


def broken(exc):
    def fail(msg):
        raise exc
    return fail


# ---------- 성공·다시 보내기 ----------

def test_resend_keeps_every_attempt_and_api_shows_names_only(client, session, world, outbox):
    order = approved(client, session, world)
    assert send(client, order).status_code == 200
    world["a_supplier"].email = "new@a-supplier.test"
    session.commit()
    login_as(client, "staff@a.test")  # 담당자도 보내고 볼 수 있다
    assert send(client, order, resend=True).status_code == 200
    saved = rows(session, order["id"])
    assert [(r.kind, r.result, r.to_address, r.sent_by, r.with_link, r.failure_code) for r in saved] == [
        ("ORDER", "SENT", "sales@a-supplier.test", world["a_admin"].id, True, None),
        ("ORDER", "SENT", "new@a-supplier.test", world["a_staff"].id, True, None),
    ]  # 다시 보내도 처음 기록이 남는다 (emailed_* 는 마지막 것으로 덮인다)
    assert all(r.company_id == world["a_company"].id for r in saved)
    body = client.get(f"{URL}/{order['id']}/email-log").json()
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 2}
    data = body["data"]
    assert all(set(d) == OUT_KEYS for d in data)  # 사용자 번호·이메일 칸이 없다
    assert [(d["to_address"], d["sent_by_name"]) for d in data] == [
        ("new@a-supplier.test", world["a_staff"].name), ("sales@a-supplier.test", world["a_admin"].name)]  # 최신순
    assert "admin@a.test" not in str(data) and "staff@a.test" not in str(data)


def test_token_is_never_stored_in_log(client, session, world, outbox):
    order = approved(client, session, world)
    assert send(client, order).status_code == 200
    token = TOKEN_RE.search(outbox[-1].get_body(("plain",)).get_content()).group(1)
    values = all_values(session, order["id"])
    assert token not in values and hash_reset_token(token) not in values  # 원본도 해시도 없다
    assert "supplier-reply" not in values


def test_without_link_records_false(client, session, world, outbox, monkeypatch):
    monkeypatch.setattr(settings, "supplier_link_enabled", False)
    order = approved(client, session, world)
    assert send(client, order).status_code == 200
    assert [r.with_link for r in rows(session, order["id"])] == [False]


# ---------- 실패 ----------

@pytest.mark.parametrize(("exc", "code"), [
    (smtplib.SMTPAuthenticationError(535, RAW.encode()), "AUTH"),
    (smtplib.SMTPRecipientsRefused({"x@y.test": (550, RAW.encode())}), "RECIPIENT_REFUSED"),
    (TimeoutError(RAW), "TIMEOUT"),
    (smtplib.SMTPServerDisconnected(RAW), "CONNECTION"),
    (ConnectionRefusedError(RAW), "CONNECTION"),
    (smtplib.SMTPDataError(554, RAW.encode()), "OTHER"),
])
def test_failure_logs_code_only_and_changes_nothing_else(client, session, world, outbox, monkeypatch, exc, code):
    order = approved(client, session, world)
    monkeypatch.setattr(po_mail, "deliver", broken(exc))
    r = send(client, order)
    assert r.status_code == 502 and r.json()["error"]["code"] == "MAIL_FAILED"
    [saved] = rows(session, order["id"])
    assert (saved.result, saved.failure_code, saved.to_address, saved.sent_by) == (
        "FAILED", code, "sales@a-supplier.test", world["a_admin"].id)
    assert RAW not in all_values(session, order["id"])  # 메일 서버 원문은 저장하지 않는다
    after = po(session, order["id"])  # 실패 커밋에 발주서 변경이 딸려 가지 않는다
    assert (after.status, after.emailed_at, after.ordered_at, after.supplier_token_hash) == ("APPROVED", None, None, None)


def test_resend_failure_commits_only_the_failure_row(client, session, world, outbox, monkeypatch):
    # 주의 1: 실패 때 커밋이 생겨도 새 토큰·만료·emailed_*·상태·변경 이력은 저장되지 않는다
    order = approved(client, session, world)
    assert send(client, order).status_code == 200
    before = po(session, order["id"])
    kept = (before.status, before.emailed_at, before.emailed_to, before.emailed_by, before.ordered_at,
            before.supplier_token_hash, before.supplier_token_expires_at)
    changes = len(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order["id"])).all())
    world["a_supplier"].email = "new@a-supplier.test"
    session.commit()
    monkeypatch.setattr(po_mail, "deliver", broken(smtplib.SMTPServerDisconnected("down")))
    assert send(client, order, resend=True).status_code == 502
    after = po(session, order["id"])
    assert (after.status, after.emailed_at, after.emailed_to, after.emailed_by, after.ordered_at,
            after.supplier_token_hash, after.supplier_token_expires_at) == kept
    assert len(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order["id"])).all()) == changes
    assert [(r.result, r.to_address) for r in rows(session, order["id"])] == [
        ("SENT", "sales@a-supplier.test"), ("FAILED", "new@a-supplier.test")]


def test_failure_row_save_error_still_returns_502(client, session, world, outbox, monkeypatch, caplog):
    order = approved(client, session, world)
    monkeypatch.setattr(po_mail, "deliver", broken(smtplib.SMTPServerDisconnected("down")))

    def db_down():
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", db_down)
    monkeypatch.setattr(po_api.log, "disabled", False)  # conftest 의 alembic 로그 설정이 꺼 둔 로거를 다시 켠다
    with caplog.at_level(logging.WARNING, logger="app.api.purchase_orders"):
        r = send(client, order)
    assert r.status_code == 502 and r.json()["error"]["code"] == "MAIL_FAILED"  # 원래 실패를 그대로 알린다
    assert f"purchase_order_id={order['id']}" in caplog.text and "@" not in caplog.text  # 주소는 로그에 없다


# ---------- 메일은 나갔는데 저장 실패 ----------

def test_unsaved_row_when_commit_fails(client, session, world, outbox, monkeypatch):
    order = approved(client, session, world)
    real_commit = session.commit

    def fail_once():
        monkeypatch.setattr(session, "commit", real_commit)
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", fail_once)
    r = send(client, order)
    assert r.status_code == 500 and r.json()["error"]["code"] == "MAIL_SENT_NOT_SAVED"
    [saved] = rows(session, order["id"])  # SENT 행은 롤백되고 UNSAVED 1행만 남는다
    assert (saved.result, saved.failure_code, saved.to_address, saved.with_link) == ("UNSAVED", None, "sales@a-supplier.test", True)
    token = TOKEN_RE.search(outbox[-1].get_body(("plain",)).get_content()).group(1)
    assert token not in all_values(session, order["id"]) and hash_reset_token(token) not in all_values(session, order["id"])
    after = po(session, order["id"])
    assert (after.status, after.emailed_at, after.supplier_token_hash) == ("APPROVED", None, None)


def test_unsaved_row_save_error_logs_order_id_only(client, session, world, outbox, monkeypatch, caplog):
    order = approved(client, session, world)

    def db_down():
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", db_down)
    monkeypatch.setattr(po_api.log, "disabled", False)  # conftest 의 alembic 로그 설정이 꺼 둔 로거를 다시 켠다
    with caplog.at_level(logging.WARNING, logger="app.api.purchase_orders"):
        r = send(client, order)
    assert r.status_code == 500 and r.json()["error"]["code"] == "MAIL_SENT_NOT_SAVED"
    assert f"purchase_order_id={order['id']}" in caplog.text
    assert "@" not in caplog.text and "supplier-reply" not in caplog.text  # 주소·링크는 로그에 없다


# ---------- 기록하지 않는 경우 ----------

def test_requests_stopped_before_smtp_are_not_logged(client, session, world, outbox, monkeypatch):
    order = approved(client, session, world, email=None)
    assert send(client, order).status_code == 409  # NO_SUPPLIER_EMAIL
    world["a_supplier"].email = "sales@a-supplier.test"
    session.commit()
    monkeypatch.setattr(settings, "smtp_host", "")
    assert send(client, order).status_code == 503  # MAIL_NOT_CONFIGURED
    assert rows(session, order["id"]) == []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    assert send(client, order).status_code == 200
    assert send(client, order).status_code == 409  # ALREADY_ORDERED (resend 없이)
    assert [r.result for r in rows(session, order["id"])] == ["SENT"]


# ---------- 조회 권한·회사 분리·추가 전용 ----------

def test_other_company_cannot_read_log(client, session, world, outbox):
    order = approved(client, session, world)
    assert send(client, order).status_code == 200
    login_as(client, "admin@b.test")
    assert client.get(f"{URL}/{order['id']}/email-log").status_code == 404


def test_no_route_can_modify_or_delete_log():
    paths = {p: sorted(ops) for p, ops in app.openapi()["paths"].items() if "email-log" in p}
    assert paths == {"/api/v1/purchase-orders/{order_id}/email-log": ["get"]}


# ---------- 동시 발송 (진짜 commit) ----------

def test_concurrent_resends_are_serialized_and_both_logged(engine, committed_company, monkeypatch):
    # 다시 보내기는 서버가 막지 않는다(#259 B). 발주서 잠금으로 한 줄로 서고, 보낸 만큼 이력이 남으며 멈추지 않는다
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(settings, "supplier_link_enabled", False)
    monkeypatch.setattr(po_mail, "deliver", sent.append)
    data = committed_company
    order_id, _ = ordered_po(engine, data, [data["product_id"]])

    def set_email(s):
        s.scalar(select(Supplier).where(Supplier.company_id == data["company_id"])).email = "cc@supplier.test"

    run_in_new_session(engine, set_email)
    resend = lambda: run_in_new_session(engine, lambda s: po_mail.send_order(
        data["company_id"], s, s.get(User, data["admin_id"]), order_id, "다시 보냅니다.", True))
    results = run_at_once(hold_row_lock(engine, PurchaseOrder, order_id), delayed(resend), delayed(resend))
    assert not any(isinstance(r, Exception) for r in results[1:])
    saved = run_in_new_session(engine, lambda s: [(r.result, r.sent_by) for r in s.scalars(
        select(PoEmailLog).where(PoEmailLog.purchase_order_id == order_id))])
    assert saved == [("SENT", data["admin_id"])] * 2 and len(sent) == 2
