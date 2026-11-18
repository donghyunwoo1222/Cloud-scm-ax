"""공급업체 확인 링크 (#265 PR2): 메일 토큰 발급·공개 API 보기·확인·회신. 메일은 가짜 서버(monkeypatch), 서버 실행 없음.

토큰 원본 값은 테스트 안에서만 쓰고 출력하지 않는다(assert 메시지에도 넣지 않는다).
"""

import hashlib  # 기준 본문 해시
import logging  # 로그 캡처
import re  # 메일 본문에서 토큰 꺼내기
import smtplib  # 발송 실패 흉내
from datetime import timedelta  # 날짜 범위

import pytest  # 테스트 도구
from sqlalchemy import func, select  # DB 시각, 조회

from app.auth.security import hash_reset_token  # 저장되는 해시
from app.clock import seoul_today  # 서울 기준 오늘
from app.config import settings  # 스위치·주소 (테스트 동안만 바꾼다)
from app.models import PoChangeLog, PurchaseOrder  # 확인할 표
from app.services import po_mail, supplier_reply  # 대상
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_document import make_order  # 승인된 발주서 (P1 55개, P2 40개)
from tests.test_po_pdf import make_doc  # DB 없는 문서 dict

URL = "/api/v1/purchase-orders"
PUBLIC = "/api/v1/supplier-reply"
TOKEN_RE = re.compile(r"/supplier-reply#([A-Za-z0-9_-]+)")
INVALID = {"error": {"code": "SUPPLIER_LINK_INVALID", "message": supplier_reply.INVALID_MESSAGE, "details": None}}


@pytest.fixture
def outbox(monkeypatch):
    """가짜 메일 서버 + 링크 켜짐(https). 보낸 메일은 목록에 담긴다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(settings, "app_base_url", "https://scm.test")
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    monkeypatch.setattr(po_mail, "deliver", sent.append)
    return sent


def token_in(msg) -> str | None:
    """메일 글자 본문의 링크 토큰 (없으면 None)."""
    found = TOKEN_RE.search(msg.get_body(("plain",)).get_content())
    return found.group(1) if found else None


def send(client, order, resend=False):
    return client.post(f"{URL}/{order['id']}/email", json={"intro": "안녕하세요.", "resend": resend})


def sent_order(client, session, world, outbox):
    """승인 → 메일 발송(ORDERED) → (발주 응답, 토큰)."""
    world["a_supplier"].email = "sales@a-supplier.test"
    session.commit()
    order, _ = make_order(client, session, world)
    r = send(client, order)
    assert r.status_code == 200
    return r.json()["data"], token_in(outbox[-1])


def view(client, token):
    return client.post(f"{PUBLIC}/view", json={"token": token})


def confirm(client, token, due=None):
    body = {"token": token} if due is None else {"token": token, "due_date": due.isoformat()}
    return client.post(f"{PUBLIC}/confirm", json=body)


def row(session, order) -> PurchaseOrder:
    session.expire_all()  # API 가 바꾼 값을 다시 읽는다
    return session.get(PurchaseOrder, order["id"])


def logs(session, order) -> list[PoChangeLog]:
    return list(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order["id"]).order_by(PoChangeLog.id)))


def supplier_logs(session, order) -> list[tuple]:
    return [(r.field, r.old_value, r.new_value) for r in logs(session, order) if r.field.startswith("supplier_")]


# ---------- 메일 본문: 링크가 없으면 PR 이전과 글자 하나까지 같다 ----------

# PR 이전 코드(origin/main 35e1198 의 po_mail.fixed_html/fixed_text)로 make_doc() 출력을 만든 SHA-256.
# 긴 문자열 대신 해시만 둔다. make_doc(test_po_pdf.py)을 바꾸면 이 값도 다시 만들어야 한다:
#   git show 35e1198:backend/app/services/po_mail.py 를 임시 모듈로 불러 같은 doc 로 해시를 낸다.
BASELINE = {
    ("basic", "fixed_html"): "d2a5908e6c8949cc4c6b2cf4eb6f8d3fc8069f6f819b62d266b293512c9e4043",
    ("basic", "fixed_text"): "b002fad34ab43439b2340e4ef0cd63008b6404933debed981a3c41eac8652019",
    ("changed", "fixed_html"): "b40e04c6a7d64be8b6df6d4866966c77952a0e1fe0ebbd7c1d19194178a60a9d",
    ("changed", "fixed_text"): "79d334a8308d326dad42c886cb9f0523de536f04e03ee8380554f5b1c6f31dad",
}


def test_body_without_link_is_byte_identical_to_before():
    docs = {"basic": make_doc(), "changed": make_doc(buyer="새상호", company="옛상호")}
    for (name, fn_name), expected in BASELINE.items():
        out = getattr(po_mail, fn_name)(docs[name])  # link=None (스위치 꺼짐·http 주소일 때 send_order 가 넘기는 값)
        assert hashlib.sha256(out.encode()).hexdigest() == expected, (name, fn_name)


@pytest.mark.parametrize("enabled, base, has_link", [
    (False, "https://scm.test", False),  # 스위치 꺼짐
    (True, "http://scm.test", False),  # https 아님
    (True, "", False),  # 주소 없음
    (True, "http://localhost.evil.test", False),  # localhost 로 시작만 하는 주소
    (True, "http://localhost:3000", True),  # 로컬 시험 예외
    (True, "https://scm.test/", True),
])
def test_link_only_when_enabled_and_https(client, session, world, outbox, monkeypatch, enabled, base, has_link):
    monkeypatch.setattr(settings, "supplier_link_enabled", enabled)
    monkeypatch.setattr(settings, "app_base_url", base)
    order, token = sent_order(client, session, world, outbox)
    assert (token is not None) == has_link
    if not has_link:  # 본문은 앞머리 + PR 이전과 같은 고정 부분 그대로, 토큰도 저장 안 함
        doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
        assert outbox[-1].get_body(("plain",)).get_content().rstrip("\n") == f"안녕하세요.\n\n{po_mail.fixed_text(doc)}"
        assert "supplier-reply" not in outbox[-1].get_body(("html",)).get_content()
        assert row(session, order).supplier_token_hash is None
    else:
        assert f"{base.rstrip('/')}/supplier-reply#" in outbox[-1].get_body(("html",)).get_content()


def test_switch_off_makes_public_api_404(client, session, world, outbox, monkeypatch):
    _, token = sent_order(client, session, world, outbox)
    assert view(client, token).status_code == 200
    monkeypatch.setattr(settings, "supplier_link_enabled", False)
    for r in (view(client, token), confirm(client, token)):
        assert r.status_code == 404 and r.json() == INVALID


def test_preview_shows_placeholder_not_token(client, session, world, outbox):
    world["a_supplier"].email = "sales@a-supplier.test"
    session.commit()
    order, _ = make_order(client, session, world)
    html = client.get(f"{URL}/{order['id']}/email").json()["data"]["fixed_html"]
    assert po_mail.LINK_PREVIEW in html and "supplier-reply" not in html and "<a href" not in html


# ---------- 토큰: 해시만 저장, 원본은 메일 본문에만 ----------

def test_token_only_in_mail_body(client, session, world, outbox, caplog):
    caplog.set_level(logging.DEBUG)
    order, token = sent_order(client, session, world, outbox)
    po = row(session, order)
    assert len(token) >= 43 and po.supplier_token_hash == hash_reset_token(token)
    assert po.supplier_token_expires_at is not None
    gap = session.scalar(select(func.now())) + timedelta(days=30) - po.supplier_token_expires_at
    assert timedelta(0) <= gap < timedelta(minutes=5)  # 발송 시각 + 30일
    values = [str(getattr(po, c.key)) for c in PurchaseOrder.__table__.columns]  # 발주서 행 모든 칸 (발송 기록 emailed_* 포함)
    values += [f"{r.field}{r.old_value}{r.new_value}{r.reason}" for r in logs(session, order)]  # 변경 이력
    assert not any(token in v for v in values)
    assert token not in caplog.text
    sent_response = send(client, order, resend=True).text  # 발송 응답
    assert token not in sent_response and "supplier_token" not in sent_response  # 해시·만료도 응답에 없다


def test_invalid_expired_old_tokens_same_404(client, session, world, outbox):
    order, old = sent_order(client, session, world, outbox)
    assert send(client, order, resend=True).status_code == 200  # 다시 보내면 새 토큰
    new = token_in(outbox[-1])
    assert new != old and view(client, new).status_code == 200
    po = row(session, order)
    po.supplier_token_expires_at = func.now() - timedelta(seconds=1)
    session.commit()
    expired = new
    for token in (old, expired, "x" * 43):  # 옛 토큰 · 만료 · 없는 토큰
        for r in (view(client, token), confirm(client, token)):
            assert r.status_code == 404 and r.json() == INVALID


def test_resend_failure_keeps_old_token(client, session, world, outbox, monkeypatch):
    order, old = sent_order(client, session, world, outbox)
    before = row(session, order).supplier_token_hash

    def broken(msg):
        raise smtplib.SMTPServerDisconnected("down")

    monkeypatch.setattr(po_mail, "deliver", broken)
    assert send(client, order, resend=True).status_code == 502
    assert row(session, order).supplier_token_hash == before  # 발송 실패: 옛 링크 그대로 유효
    assert view(client, old).status_code == 200


def test_mail_sent_not_saved_mentions_resend_button(client, session, world, outbox, monkeypatch):
    order, old = sent_order(client, session, world, outbox)
    real_commit = session.commit

    def fail_once():
        monkeypatch.setattr(session, "commit", real_commit)
        raise RuntimeError("db down")

    monkeypatch.setattr(session, "commit", fail_once)
    r = send(client, order, resend=True)
    assert r.status_code == 500 and r.json()["error"]["code"] == "MAIL_SENT_NOT_SAVED"
    assert "'다시 보내기'" in r.json()["error"]["message"]  # mail-panel.tsx 의 버튼 이름
    new = token_in(outbox[-1])
    assert view(client, new).status_code == 404 and view(client, old).status_code == 200  # 저장 안 됨: 옛 링크만 유효
    monkeypatch.setattr(settings, "supplier_link_enabled", False)  # 링크를 안 넣은 발송이면 덧붙이지 않는다
    monkeypatch.setattr(session, "commit", fail_once)
    assert "다시 보내기" not in send(client, order, resend=True).json()["error"]["message"]


# ---------- 공개 응답: 허용 칸 고정 ----------

def assert_public_shape(data):
    assert tuple(data) == supplier_reply.PUBLIC_KEYS
    assert all(tuple(i) == supplier_reply.ITEM_KEYS for i in data["items"])


def test_view_and_confirm_expose_only_allowed_fields(client, session, world, outbox):
    company, supplier = world["a_company"], world["a_supplier"]
    company.business_number, company.address, company.phone = "9876543210", "ADDR-SECRET", "PHONE-SECRET"
    supplier.contact_name, supplier.phone = "CONTACT-SECRET", "SUPPHONE-SECRET"
    session.commit()
    order, token = sent_order(client, session, world, outbox)
    po = row(session, order)
    po.memo, po.payment_terms, po.delivery_address = "MEMO-SECRET", "TERMS-SECRET", "DELIVERY-SECRET"
    session.commit()
    for r in (view(client, token), confirm(client, token, seoul_today() + timedelta(days=3))):
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        data = r.json()["data"]
        assert_public_shape(data)
        assert data["state"] == "REPLYABLE" and data["buyer_name"] == "회사A" and data["po_number"] == order["po_number"]
        assert [(i["quantity"], i["unit"]) for i in data["items"]] == [(55, "개"), (40, "개")]
        text = r.text
        for secret in ("SECRET", "9876543210", "8000", "6500", "sales@a-supplier.test", "admin@a.test", "a-ADMIN", "company_id", '"P1"', "sku"):
            assert secret not in text, secret
    assert data["supplier_due_date"] == (seoul_today() + timedelta(days=3)).isoformat() and data["supplier_confirmed_at"]


def test_request_rejects_extra_fields(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    for path in ("view", "confirm"):
        for extra in ({"company_id": world["b_company"].id}, {"purchase_order_id": order["id"]}):
            r = client.post(f"{PUBLIC}/{path}", json={"token": token, **extra})
            assert r.status_code == 422 and token not in r.text


def test_other_company_untouched(client, session, world, outbox):
    _, token = sent_order(client, session, world, outbox)
    b_logs = session.scalar(select(func.count()).select_from(PoChangeLog).where(PoChangeLog.company_id == world["b_company"].id))
    data = confirm(client, token, seoul_today() + timedelta(days=2)).json()["data"]
    assert data["buyer_name"] == "회사A" and "회사B" not in str(data)
    assert session.scalar(select(func.count()).select_from(PoChangeLog).where(PoChangeLog.company_id == world["b_company"].id)) == b_logs


def test_errors_never_echo_token(client, session, world, outbox):
    _, token = sent_order(client, session, world, outbox)
    responses = [
        client.post(f"{PUBLIC}/view", json={"token": token + "x" * 100}),  # 길이 초과 422
        client.post(f"{PUBLIC}/view", json={"token": token, "extra": token}),  # 모르는 칸 422
        client.post(f"{PUBLIC}/confirm", content=f'{{"token": "{token}", ', headers={"content-type": "application/json"}),  # 깨진 JSON
        confirm(client, token, seoul_today() - timedelta(days=1)),  # 날짜 범위 422
        view(client, token[:-1] + ("A" if token[-1] != "A" else "B")),  # 없는 토큰 404
    ]
    assert [r.status_code for r in responses] == [422, 422, 422, 422, 404]
    for r in responses:
        assert token not in r.text and token[:20] not in r.text


# ---------- 보기는 아무것도 바꾸지 않는다 ----------

def snapshot(session, order):
    po = row(session, order)
    return {c.key: getattr(po, c.key) for c in PurchaseOrder.__table__.columns}, len(logs(session, order))


def test_view_changes_nothing(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    before = snapshot(session, order)
    for _ in range(3):
        assert view(client, token).status_code == 200
    assert snapshot(session, order) == before


# ---------- 상태별 ----------

def receive(client, order, *quantities):
    items = [{"purchase_order_item_id": i["id"], "quantity": q} for i, q in zip(order["items"], quantities, strict=True) if q]
    r = client.post(f"{URL}/{order['id']}/receipts", json={"items": items})
    assert r.status_code in (200, 201), r.json()
    return r


def test_cancelled_view_shows_notice_only_and_confirm_rejected(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    assert client.post(f"{URL}/{order['id']}/cancel", json={"reason": "공급 중단"}).status_code == 200
    data = view(client, token).json()["data"]
    assert_public_shape(data)
    assert data == {**dict.fromkeys(supplier_reply.PUBLIC_KEYS), "state": "CANCELLED", "notice": "취소된 발주입니다",
                    "can_reply": False, "items": []}
    r = confirm(client, token, seoul_today() + timedelta(days=1))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SUPPLIER_REPLY_CLOSED"


def test_received_view_only(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    receive(client, order, 55, 40)  # 모두 입고 → RECEIVED
    data = view(client, token).json()["data"]
    assert data["state"] == "RECEIVED" and data["notice"] == "입고 완료된 발주입니다" and data["items"]
    assert confirm(client, token).status_code == 409


def test_partial_receipt_can_reply_then_closed(client, session, world, outbox):
    order2, token2 = sent_order(client, session, world, outbox)
    receive(client, order2, 50, 0)  # 부분 입고: 회신 가능
    assert confirm(client, token2, seoul_today() + timedelta(days=1)).status_code == 200
    assert client.post(f"{URL}/{order2['id']}/close-remaining", json={"reason": "잔량 미납"}).status_code == 200
    data = view(client, token2).json()["data"]
    assert data["state"] == "RECEIVED_CLOSED" and data["notice"] == "입고 완료(남은 수량은 받지 않기로 함)"
    assert confirm(client, token2).status_code == 409


def test_approved_with_token_is_404(client, session, world, outbox):
    order, _ = make_order(client, session, world)  # 승인만 (토큰은 발송 때만 생기지만 안전망 확인)
    po = row(session, order)
    po.supplier_token_hash = hash_reset_token("approved-token")
    po.supplier_token_expires_at = func.now() + timedelta(days=1)
    session.commit()
    assert view(client, "approved-token").json() == INVALID and confirm(client, "approved-token").json() == INVALID


# ---------- 확인·회신 규칙 ----------

def test_confirm_only_records_time_once(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    data = confirm(client, token).json()["data"]
    assert data["supplier_confirmed_at"] and data["supplier_due_date"] is None and data["replies_left"] == 5
    first = row(session, order).supplier_confirmed_at
    assert confirm(client, token).status_code == 200
    po = row(session, order)
    assert po.supplier_confirmed_at == first and po.supplier_reply_count == 0
    assert [f for f, _, _ in supplier_logs(session, order)] == ["supplier_confirmed_at"]


def test_change_log_rows_are_by_supplier(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    d1, d2 = seoul_today() + timedelta(days=3), seoul_today() + timedelta(days=5)
    confirm(client, token, d1)
    confirm(client, token, d2)
    rows = [r for r in logs(session, order) if r.field.startswith("supplier_")]
    assert all(r.changed_by is None for r in rows)
    assert [(f, o, n) for f, o, n in supplier_logs(session, order) if f == "supplier_due_date"] == [
        ("supplier_due_date", None, d1.isoformat()), ("supplier_due_date", d1.isoformat(), d2.isoformat())]
    login_as(client, "admin@a.test")
    listed = client.get(f"{URL}/{order['id']}/change-log").json()["data"]
    assert {r["changed_by_name"] for r in listed if r["field"].startswith("supplier_")} == {"공급업체(메일 링크)"}
    assert row(session, order).supplier_reply_count == 2


def test_reply_limit_order_of_checks(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    for days in range(1, 6):  # 서로 다른 날짜 5번
        assert confirm(client, token, seoul_today() + timedelta(days=days)).status_code == 200
    last = seoul_today() + timedelta(days=5)
    before = len(logs(session, order))
    # (1) 같은 날짜 재전송: 제한보다 먼저 판단 → 변화 없는 200
    r = confirm(client, token, last)
    assert r.status_code == 200 and r.json()["data"]["replies_left"] == 0
    assert len(logs(session, order)) == before and row(session, order).supplier_reply_count == 5
    # (2) 확인만: 5번을 다 써도 성공, 횟수 불변
    assert confirm(client, token).status_code == 200
    assert row(session, order).supplier_reply_count == 5 and len(logs(session, order)) == before
    # (3) 날짜가 실제로 바뀌는 6번째만 409
    r = confirm(client, token, seoul_today() + timedelta(days=6))
    assert r.status_code == 409 and r.json()["error"]["code"] == "SUPPLIER_REPLY_LIMIT"
    po = row(session, order)
    assert po.supplier_due_date == last and po.supplier_reply_count == 5


def test_due_date_range(client, session, world, outbox):
    order, token = sent_order(client, session, world, outbox)
    today = seoul_today()
    for bad in (today - timedelta(days=1), supplier_reply.one_year_later(today) + timedelta(days=1)):
        r = confirm(client, token, bad)
        assert r.status_code == 422 and r.json()["error"]["details"] == [{"field": "due_date", "reason": "out_of_range"}]
    for good in (today, supplier_reply.one_year_later(today)):
        assert confirm(client, token, good).status_code == 200
    assert row(session, order).supplier_reply_count == 2


def test_one_year_later_leap_day():
    from datetime import date
    assert supplier_reply.one_year_later(date(2028, 2, 29)) == date(2029, 2, 28)
    assert supplier_reply.one_year_later(date(2026, 11, 18)) == date(2027, 11, 18)
