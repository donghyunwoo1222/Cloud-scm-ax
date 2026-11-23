"""납기 지연 독촉 메일 (#269): 스위치·지연 판단·미리보기·발송·이력·한도·링크·실패·저장 실패·동시 요청·회사 분리.

메일은 가짜 서버(monkeypatch), 서버 실행 없음. 토큰 원본 값은 테스트 안에서만 쓰고 출력하지 않는다.
시각: 테스트 하나는 바깥 트랜잭션 하나라 DB now() 가 고정된다. 간격이 지난 상황은 이력 행 시각을 앞당겨 만든다.
"""

import smtplib  # 실패 흉내
from datetime import timedelta  # 납기·이력 시각 조정

import pytest  # 테스트 도구
from sqlalchemy import select, update  # 조회, 이력 시각 앞당기기 (테스트 준비만)

from app.auth.security import hash_reset_token  # 저장된 토큰 해시 비교
from app.clock import seoul_today  # 서울 기준 오늘
from app.config import Settings, settings  # 기본값 확인, 테스트 동안만 바꾸는 설정
from app.main import app  # 등록된 경로 목록
from app.models import (
    PoChangeLog,
    PoEmailLog,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.services import po_mail, po_reminder  # 가짜 발송 자리, 대상
from tests.concurrency import delayed, hold_row_lock, ordered_po, run_at_once, run_in_new_session
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_document import make_order  # 승인된 발주서 (P1 55개, P2 40개)
from tests.test_supplier_reply import TOKEN_RE  # 메일 본문의 링크 토큰 모양

URL = "/api/v1/purchase-orders"
TODAY = seoul_today()


@pytest.fixture
def outbox(monkeypatch):
    """가짜 메일 서버 + 독촉 켜짐 + 확인 링크 꺼짐(링크 테스트만 켠다). 보낸 메일은 목록에 담긴다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(settings, "app_base_url", "https://scm.test")
    monkeypatch.setattr(settings, "supplier_link_enabled", False)
    monkeypatch.setattr(settings, "po_reminder_enabled", True)
    monkeypatch.setattr(po_mail, "deliver", sent.append)

    def no_network(*args, **kwargs):  # deliver 를 거치지 않고 SMTP 를 열면 바로 실패
        raise AssertionError("테스트에서 실제 SMTP 접속 시도")
    monkeypatch.setattr(smtplib, "SMTP", no_network)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_network)
    return sent


def overdue(client, session, world, days=2, email="sales@a-supplier.test", via_email=False) -> dict:
    """납기가 days 일 지난 ORDERED 발주서 (관리자로 로그인된 채 끝난다). via_email 이면 발주서 메일로 ORDERED 가 된다."""
    world["a_supplier"].email = email
    session.commit()
    order, _ = make_order(client, session, world)
    if via_email:
        assert client.post(f"{URL}/{order['id']}/email", json={"intro": "발주드립니다."}).status_code == 200
    else:
        assert client.post(f"{URL}/{order['id']}/order").status_code == 200
    set_due(session, order["id"], TODAY - timedelta(days=days))
    return order


def set_due(session, order_id, due, supplier_due=None):
    po = session.get(PurchaseOrder, order_id)
    po.due_date, po.supplier_due_date = due, supplier_due
    session.commit()


def preview(client, order):
    return client.get(f"{URL}/{order['id']}/reminder")


def remind(client, order, intro="납기 확인 부탁드립니다."):
    return client.post(f"{URL}/{order['id']}/reminder", json={"intro": intro})


def code(r):
    return r.status_code, r.json()["error"]["code"]


def rows(session, order_id) -> list[PoEmailLog]:
    session.expire_all()
    return list(session.scalars(select(PoEmailLog).where(PoEmailLog.purchase_order_id == order_id).order_by(PoEmailLog.id)))


def age_rows(session, order_id, hours):
    """이 발주의 이력 시각을 hours 만큼 앞당긴다 (시간이 지난 것처럼)."""
    session.execute(update(PoEmailLog).where(PoEmailLog.purchase_order_id == order_id).values(
        created_at=PoEmailLog.created_at - timedelta(hours=hours)))
    session.commit()


def broken(exc):
    def fail(msg):
        raise exc
    return fail


def plain(msg) -> str:
    return msg.get_body(("plain",)).get_content()


def html(msg) -> str:
    return msg.get_body(("html",)).get_content()


# ---------- 설정·스위치 ----------

def test_settings_defaults():
    fields = Settings.model_fields
    assert fields["po_reminder_enabled"].default is False  # 기본은 꺼짐
    assert (fields["po_reminder_interval_hours"].default, fields["po_reminder_max_per_order"].default,
            fields["po_reminder_daily_per_company"].default) == (48, 3, 20)


def test_switch_off_hides_button_and_returns_503(client, session, world, outbox, monkeypatch):
    order = overdue(client, session, world)
    assert "remind" in client.get(f"{URL}/{order['id']}").json()["data"]["allowed_actions"]
    monkeypatch.setattr(settings, "po_reminder_enabled", False)
    assert "remind" not in client.get(f"{URL}/{order['id']}").json()["data"]["allowed_actions"]
    assert code(preview(client, order)) == (503, "REMINDER_DISABLED")
    assert code(remind(client, order)) == (503, "REMINDER_DISABLED")
    assert outbox == [] and rows(session, order["id"]) == []


# ---------- 지연 판단 (receipt_due_condition 한 곳) ----------

def test_not_overdue_cases(client, session, world, outbox):
    order = overdue(client, session, world)
    set_due(session, order["id"], None)  # 납기 없음
    r = remind(client, order)
    assert code(r) == (409, "NOT_OVERDUE") and r.json()["error"]["details"] == {"reason": "NO_DUE_DATE"}
    set_due(session, order["id"], TODAY)  # 오늘이 납기: 아직 지연 아님
    r = preview(client, order)
    assert code(r) == (409, "NOT_OVERDUE")
    assert r.json()["error"]["details"] == {"due_date": TODAY.isoformat(), "supplier_due_date": None}
    # 약속 납기는 지났지만 공급업체가 회신한 납기가 아직 안 왔다 → 회신 기준으로 지연 아님
    set_due(session, order["id"], TODAY - timedelta(days=5), TODAY + timedelta(days=2))
    assert code(remind(client, order)) == (409, "NOT_OVERDUE")
    assert "remind" not in client.get(f"{URL}/{order['id']}").json()["data"]["allowed_actions"]
    # 회신 납기도 지났다 → 독촉 가능
    set_due(session, order["id"], TODAY + timedelta(days=5), TODAY - timedelta(days=1))
    assert "remind" in client.get(f"{URL}/{order['id']}").json()["data"]["allowed_actions"]
    assert remind(client, order).status_code == 200
    assert outbox and "회신 납기" in plain(outbox[-1])
    assert len(rows(session, order["id"])) == 1


def test_inactive_supplier_can_still_be_reminded(client, session, world, outbox):
    order = overdue(client, session, world)
    world["a_supplier"].is_active = False  # 비활성은 새 발주에만 영향 (이미 ORDERED 인 발주의 일은 허용)
    session.commit()
    assert remind(client, order).status_code == 200


# ---------- 미리보기 ----------

def test_preview_changes_nothing_and_never_delivers(client, session, world, outbox):
    order = overdue(client, session, world)
    before = session.get(PurchaseOrder, order["id"])
    kept = (before.status, before.emailed_at, before.supplier_token_hash)
    data = preview(client, order).json()["data"]
    assert data["to"] == "sales@a-supplier.test" and data["reply_to"] == "admin@a.test"
    assert data["subject"].startswith("[") and order["po_number"] in data["subject"]
    assert (data["sent_count"], data["max_per_order"], data["last_sent_at"], data["next_allowed_at"], data["blocked"]) == (0, 3, None, None, None)
    assert data["mail_ready"] is True and data["with_link"] is False
    assert outbox == [] and rows(session, order["id"]) == []
    session.expire_all()
    after = session.get(PurchaseOrder, order["id"])
    assert (after.status, after.emailed_at, after.supplier_token_hash) == kept


def test_preview_with_link_shows_placeholder_not_token(client, session, world, outbox, monkeypatch):
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    order = overdue(client, session, world)
    data = preview(client, order).json()["data"]
    assert data["with_link"] is True and po_mail.LINK_PREVIEW in data["fixed_html"]
    assert "supplier-reply#" not in data["fixed_html"]
    assert po_reminder.OLD_LINK_NOTE not in data["fixed_html"]  # 미리보기에는 실제 링크가 없다


# ---------- 발송 ----------

def test_send_logs_reminder_and_changes_nothing_on_order(client, session, world, outbox):
    order = overdue(client, session, world)
    before = session.get(PurchaseOrder, order["id"])
    kept = (before.status, before.emailed_at, before.emailed_to, before.emailed_by, before.ordered_at, before.supplier_token_hash)
    changes = len(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order["id"])).all())
    login_as(client, "staff@a.test")  # 담당자도 보낸다
    r = remind(client, order, "대한물산 담당자님,\n<b>확인</b> 부탁드립니다.")
    assert r.status_code == 200
    assert r.json()["data"]["sent_count"] == 1 and r.json()["data"]["next_allowed_at"]
    [msg] = outbox
    assert msg["To"] == "sales@a-supplier.test" and msg["Reply-To"] == "staff@a.test"
    assert "납기 확인 요청" in msg["Subject"] and order["po_number"] in msg["Subject"]
    assert not list(msg.iter_attachments())  # 첨부 없음
    assert "&lt;b&gt;확인&lt;/b&gt;" in html(msg) and "<b>확인</b>" not in html(msg)  # 앞머리 태그는 글자로
    [saved] = rows(session, order["id"])
    assert (saved.kind, saved.result, saved.to_address, saved.sent_by, saved.with_link, saved.failure_code) == (
        "REMINDER", "SENT", "sales@a-supplier.test", world["a_staff"].id, False, None)
    after = session.get(PurchaseOrder, order["id"])
    assert (after.status, after.emailed_at, after.emailed_to, after.emailed_by, after.ordered_at, after.supplier_token_hash) == kept
    assert len(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order["id"])).all()) == changes
    log = client.get(f"{URL}/{order['id']}/email-log").json()["data"]
    assert [(d["kind"], d["result"]) for d in log] == [("REMINDER", "SENT")]


def test_body_lists_only_remaining_lines_with_box_note(client, session, world, outbox):
    order = overdue(client, session, world)
    p1_item, p2_item = order["items"]  # P1 55개, P2 40개
    item = session.get(PurchaseOrderItem, p2_item["id"])
    item.units_per_box, item.order_unit, item.box_unit_price = 5, "박스", 32500  # P2 를 1박스=5개 박스 발주로
    session.commit()
    r = client.post(f"{URL}/{order['id']}/receipts", json={"items": [{"purchase_order_item_id": p1_item["id"], "quantity": 55}]})
    assert r.status_code in (200, 201), r.json()
    assert remind(client, order).status_code == 200
    text = plain(outbox[-1])
    assert "P1" not in text  # 다 받은 줄은 없다
    assert "40개 (= 8박스)" in text  # 박스로 나누어떨어지면 함께 적는다
    r = client.post(f"{URL}/{order['id']}/receipts", json={"items": [{"purchase_order_item_id": p2_item["id"], "quantity": 3}]})
    assert r.status_code in (200, 201), r.json()
    age_rows(session, order["id"], 49)
    assert remind(client, order).status_code == 200
    text = plain(outbox[-1])
    assert "37개" in text and "박스)" not in text  # 나누어떨어지지 않으면 낱개만


def test_build_reminder_is_pure_and_formats_boxes():
    facts = {"buyer_name": "우리상사", "supplier_name": "대한물산", "contact_name": None, "po_number": "PO-1",
             "order_date": "2026-11-01", "due_date": "2026-11-10", "supplier_due_date": None, "sender_name": "김담당",
             "lines": [{"label": "A (S1)", "remaining": 1200, "unit": "개", "boxes": (12, "박스")},
                       {"label": "B (S2)", "remaining": 7, "unit": "개", "boxes": None}]}
    mail = po_reminder.build_reminder(facts, None)
    assert mail == po_reminder.build_reminder(facts, None)  # 같은 값이면 같은 글자
    assert "1,200개 (= 12박스)" in mail["fixed_text"] and "- B (S2): 7개" in mail["fixed_text"]
    assert "대한물산 담당자님" in mail["intro"] and "회신 납기" not in mail["fixed_text"]
    assert "supplier-reply" not in mail["fixed_html"] and "김담당 담당자에게" in mail["fixed_text"]


def test_link_on_issues_new_token_and_old_link_dies(client, session, world, outbox, monkeypatch):
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    order = overdue(client, session, world, via_email=True)
    old = TOKEN_RE.search(plain(outbox[-1])).group(1)
    assert remind(client, order).status_code == 200
    body = plain(outbox[-1])
    new = TOKEN_RE.search(body).group(1)
    assert new != old and po_reminder.OLD_LINK_NOTE in body and po_reminder.OLD_LINK_NOTE in html(outbox[-1])
    session.expire_all()
    assert session.get(PurchaseOrder, order["id"]).supplier_token_hash == hash_reset_token(new)  # 옛 해시는 덮였다
    assert client.post("/api/v1/supplier-reply/view", json={"token": old}).status_code == 404
    assert client.post("/api/v1/supplier-reply/view", json={"token": new}).status_code == 200
    saved = rows(session, order["id"])[-1]
    assert (saved.kind, saved.with_link) == ("REMINDER", True)
    values = "\n".join(str(getattr(r, c.name)) for r in rows(session, order["id"]) for c in PoEmailLog.__table__.columns)
    assert new not in values and hash_reset_token(new) not in values  # 이력에는 토큰이 없다


# ---------- 실패·저장 실패 ----------

@pytest.mark.parametrize(("exc", "failure", "counted"), [
    (smtplib.SMTPAuthenticationError(535, b"x"), "AUTH", False),
    (smtplib.SMTPRecipientsRefused({"x@y.test": (550, b"x")}), "RECIPIENT_REFUSED", False),
    (ConnectionRefusedError("x"), "CONNECTION", False),
    (TimeoutError("x"), "TIMEOUT", True),  # 시간 초과는 실제로 도착했을 수 있어 센다
])
def test_failure_logs_row_keeps_token_and_counts_only_timeout(client, session, world, outbox, monkeypatch, exc, failure, counted):
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    order = overdue(client, session, world, via_email=True)
    kept = session.get(PurchaseOrder, order["id"]).supplier_token_hash
    monkeypatch.setattr(po_mail, "deliver", broken(exc))
    r = remind(client, order)
    assert code(r) == (502, "MAIL_FAILED") and r.json()["error"]["message"].endswith(po_reminder.FAILED_TAIL)
    saved = rows(session, order["id"])[-1]
    assert (saved.kind, saved.result, saved.failure_code, saved.with_link) == ("REMINDER", "FAILED", failure, True)
    session.expire_all()
    assert session.get(PurchaseOrder, order["id"]).supplier_token_hash == kept  # 실패면 옛 링크가 그대로 유효
    monkeypatch.setattr(po_mail, "deliver", outbox.append)
    r = remind(client, order)
    assert (r.status_code == 409 and r.json()["error"]["code"] == "REMINDER_TOO_SOON") if counted else r.status_code == 200


def test_unsaved_row_when_commit_fails_and_it_counts(client, session, world, outbox, monkeypatch):
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    order = overdue(client, session, world, via_email=True)
    kept = session.get(PurchaseOrder, order["id"]).supplier_token_hash
    real_commit = session.commit

    def fail_once():
        monkeypatch.setattr(session, "commit", real_commit)
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", fail_once)
    r = remind(client, order)
    assert code(r) == (500, "MAIL_SENT_NOT_SAVED") and "독촉 메일은 보냈지만" in r.json()["error"]["message"]
    [*_, saved] = rows(session, order["id"])
    assert (saved.kind, saved.result, saved.with_link) == ("REMINDER", "UNSAVED", True)  # SENT 행은 롤백되고 UNSAVED 만
    assert [r.result for r in rows(session, order["id"]) if r.kind == "REMINDER"] == ["UNSAVED"]
    new = TOKEN_RE.search(plain(outbox[-1])).group(1)
    session.expire_all()
    assert session.get(PurchaseOrder, order["id"]).supplier_token_hash == kept != hash_reset_token(new)  # 새 토큰은 저장 안 됨
    assert code(remind(client, order)) == (409, "REMINDER_TOO_SOON")  # 나간 것으로 센다


# ---------- 한도 ----------

def test_interval_then_per_order_limit(client, session, world, outbox):
    order = overdue(client, session, world)
    assert remind(client, order).status_code == 200
    r = remind(client, order)
    assert code(r) == (409, "REMINDER_TOO_SOON") and set(r.json()["error"]["details"]) == {"next_allowed_at"}
    assert preview(client, order).json()["data"]["blocked"] == "REMINDER_TOO_SOON"
    age_rows(session, order["id"], 47)  # 아직 48시간 전
    assert code(remind(client, order)) == (409, "REMINDER_TOO_SOON")
    age_rows(session, order["id"], 2)  # 49시간 지남
    assert remind(client, order).status_code == 200
    age_rows(session, order["id"], 49)
    assert remind(client, order).status_code == 200  # 3번째
    age_rows(session, order["id"], 49)
    r = remind(client, order)
    assert code(r) == (409, "REMINDER_LIMIT") and r.json()["error"]["details"] == {"count": 3, "limit": 3}
    assert preview(client, order).json()["data"]["blocked"] == "REMINDER_LIMIT"
    assert len(outbox) == 3 and [x.result for x in rows(session, order["id"])] == ["SENT"] * 3  # 409 는 기록하지 않는다


def test_company_daily_limit(client, session, world, outbox, monkeypatch):
    monkeypatch.setattr(settings, "po_reminder_daily_per_company", 1)
    first = overdue(client, session, world)
    supplier_id, product_id = world["a_supplier"].id, first["items"][0]["product_id"]
    second = client.post(URL, json={"supplier_id": supplier_id, "items": [{"product_id": product_id, "quantity": 5, "unit_price": 100}]}).json()["data"]
    for action in ("approve", "order"):
        assert client.post(f"{URL}/{second['id']}/{action}").status_code == 200
    set_due(session, second["id"], TODAY - timedelta(days=1))
    assert remind(client, first).status_code == 200
    r = remind(client, second)
    assert code(r) == (409, "REMINDER_DAILY_LIMIT") and r.json()["error"]["details"] == {"limit": 1}
    assert rows(session, second["id"]) == []


# ---------- 막히는 경우: 메일 서버에 가지 않고 기록도 없다 ----------

def test_no_email_and_not_configured(client, session, world, outbox, monkeypatch):
    order = overdue(client, session, world, email=None)
    assert preview(client, order).json()["data"]["to"] is None  # 미리보기는 열리고 화면이 안내한다
    assert code(remind(client, order)) == (409, "NO_SUPPLIER_EMAIL")
    world["a_supplier"].email = "sales@a-supplier.test"
    session.commit()
    monkeypatch.setattr(settings, "smtp_host", "")
    assert preview(client, order).json()["data"]["mail_ready"] is False
    assert code(remind(client, order)) == (503, "MAIL_NOT_CONFIGURED")
    assert outbox == [] and rows(session, order["id"]) == []


def test_intro_validation(client, session, world, outbox):
    order = overdue(client, session, world)
    assert client.post(f"{URL}/{order['id']}/reminder", json={"intro": ""}).status_code == 422
    assert client.post(f"{URL}/{order['id']}/reminder", json={"intro": "x" * 2001}).status_code == 422
    r = client.post(f"{URL}/{order['id']}/reminder", json={"intro": "x", "to": "evil@x.test"})
    assert r.status_code == 422  # 받는 주소를 바꿔치기할 수 없다
    assert outbox == []


def test_other_company_gets_404(client, session, world, outbox):
    order = overdue(client, session, world)
    login_as(client, "admin@b.test")
    assert preview(client, order).status_code == 404
    assert remind(client, order).status_code == 404
    assert outbox == []


def test_only_get_and_post_routes_exist():
    paths = {p: sorted(ops) for p, ops in app.openapi()["paths"].items() if p.endswith("/reminder")}
    assert paths == {"/api/v1/purchase-orders/{order_id}/reminder": ["get", "post"]}


# ---------- 동시 요청 (진짜 commit) ----------

def test_concurrent_reminders_send_only_once(engine, committed_company, monkeypatch):
    # 직원 둘이 같은 순간에 눌러도 발주서 잠금 + 잠금 안의 간격 검사로 한 통만 나간다
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(settings, "supplier_link_enabled", False)
    monkeypatch.setattr(settings, "po_reminder_enabled", True)
    monkeypatch.setattr(po_mail, "deliver", sent.append)
    data = committed_company
    order_id, _ = ordered_po(engine, data, [data["product_id"]])

    def prepare(s):
        s.scalar(select(Supplier).where(Supplier.company_id == data["company_id"])).email = "cc@supplier.test"
        s.get(PurchaseOrder, order_id).due_date = TODAY - timedelta(days=3)

    run_in_new_session(engine, prepare)
    send = lambda: run_in_new_session(engine, lambda s: po_reminder.send_reminder(
        data["company_id"], s, s.get(User, data["admin_id"]), order_id, "확인 부탁드립니다."))
    results = run_at_once(hold_row_lock(engine, PurchaseOrder, order_id), delayed(send), delayed(send))
    errors = [r for r in results[1:] if isinstance(r, Exception)]
    assert len(errors) == 1 and errors[0].code == "REMINDER_TOO_SOON"
    saved = run_in_new_session(engine, lambda s: [(r.kind, r.result) for r in s.scalars(
        select(PoEmailLog).where(PoEmailLog.purchase_order_id == order_id))])
    assert saved == [("REMINDER", "SENT")] and len(sent) == 1


# ---------- 응답에 예외 이름 없음 · 품목명 이스케이프 (후속) ----------

def test_failure_response_hides_exception_name_for_reminder_and_order(client, session, world, outbox, monkeypatch):
    """502 응답에는 예외 클래스 이름·원문이 없고 고정 분류 코드만 있다 (독촉·발주서 메일 둘 다)."""
    class SecretBoom(smtplib.SMTPException):  # 이름·원문이 응답에 새는지 보려는 가짜 예외
        pass
    order = overdue(client, session, world)
    monkeypatch.setattr(po_mail, "deliver", broken(SecretBoom("secret-raw-text")))
    for r in (remind(client, order), client.post(f"{URL}/{order['id']}/email", json={"intro": "x", "resend": True})):
        assert code(r) == (502, "MAIL_FAILED") and r.json()["error"]["details"] == {"failure_code": "OTHER"}
        assert "SecretBoom" not in r.text and "secret-raw-text" not in r.text


def test_product_name_is_escaped_in_reminder_preview_and_mail(client, session, world, outbox):
    evil = '<script>alert(1)</script> & "q"'
    order = overdue(client, session, world)
    session.execute(update(Product).where(Product.sku == "P1").values(name=evil))
    session.commit()
    shown = preview(client, order).json()["data"]["fixed_html"]
    assert remind(client, order).status_code == 200
    sent = html(outbox[-1])
    for body in (shown, sent):
        assert "<script>" not in body and "&lt;script&gt;alert(1)&lt;/script&gt; &amp; &quot;q&quot;" in body
