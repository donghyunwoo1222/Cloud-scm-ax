"""가짜 HTTP 전송으로 메일 제공자 설정, 발송과 실패 이력을 확인한다."""

import json  # Resend에 보낼 JSON 확인
import re  # OTP 본문에서 코드 추출
import traceback  # 예외 체인에 키가 남았는지 확인
from base64 import b64decode  # 첨부 파일이 원래 바이너리인지 확인

import httpx2
import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings, settings
from app.services import po_mail
from tests.test_login_otp import ADMIN, login, verify
from tests.test_po_email_log import URL, all_values, approved, po, rows, send
from tests.test_prod_safety import GOOD
from tests.test_supplier_doc_leak import INTERNAL_IDS, MEMO, SECRETS, doc  # noqa: F401

FAKE_KEY = "re_test_only_never_a_real_key"
FROM = "sender@scm.test"


@pytest.fixture
def resend_http(monkeypatch):
    """SMTP 설정을 비우고 실제 HTTP 요청 대신 메모리 전송기를 쓴다."""
    monkeypatch.setattr(settings, "mail_provider", "resend")
    monkeypatch.setattr(settings, "resend_from", FROM)
    monkeypatch.setattr(settings, "resend_api_key", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "smtp_host", "")
    monkeypatch.setattr(settings, "smtp_from", "")
    calls = []

    def configure(status):
        def respond(request):
            assert request.method == "POST"
            assert str(request.url) == "https://api.resend.com/emails"
            assert request.headers["Authorization"] == f"Bearer {FAKE_KEY}"
            assert request.extensions["timeout"]["read"] == 10
            assert FAKE_KEY.encode() not in request.content
            calls.append(json.loads(request.content))
            if status is None:
                # 실제 클라이언트가 민감한 요청을 예외에 붙이는 경우를 재현한다.
                raise httpx2.ReadTimeout(FAKE_KEY, request=request)
            return httpx2.Response(status, json={"id": "test-id"} if status == 200 else {"message": FAKE_KEY})

        def post(*args, **kwargs):
            with httpx2.Client(transport=httpx2.MockTransport(respond)) as client:
                return client.post(*args, **kwargs)

        monkeypatch.setattr(po_mail.httpx2, "post", post)
        return calls

    return configure


def test_resend_order_sends_both_bodies_and_attachments(client, session, world, resend_http):
    calls = resend_http(200)
    order = approved(client, session, world)
    preview = client.get(f"{URL}/{order['id']}/email").json()["data"]
    assert preview["mail_ready"] is True

    response = send(client, order)
    assert response.status_code == 200
    assert po(session, order["id"]).status == "ORDERED"
    assert [row.result for row in rows(session, order["id"])] == ["SENT"]
    payload, = calls
    assert payload["from"].endswith(f"<{FROM}>")
    assert payload["to"] == [preview["to"]]
    assert payload["reply_to"] == [preview["reply_to"]]
    assert payload["subject"] == preview["subject"]
    assert "안녕하세요." in payload["text"] and preview["fixed_html"] in payload["html"]
    pdf, xlsx = payload["attachments"]
    assert [pdf["filename"], xlsx["filename"]] == preview["attachments"]
    assert b64decode(pdf["content"]).startswith(b"%PDF")
    assert b64decode(xlsx["content"]).startswith(b"PK")


@pytest.mark.parametrize(("status", "code"), [
    (429, "CONNECTION"), (500, "CONNECTION"), (503, "CONNECTION"),
    (None, "TIMEOUT"), (401, "AUTH"), (422, "OTHER"),
])
def test_resend_failure_records_safe_code(client, session, world, resend_http, caplog, monkeypatch, status, code):
    calls = resend_http(status)
    order = approved(client, session, world)
    errors = []
    original = po_mail.failure

    def capture(exc):
        errors.append("".join(traceback.format_exception(exc)))
        assert exc.__context__ is None
        return original(exc)

    monkeypatch.setattr(po_mail, "failure", capture)
    response = send(client, order)
    assert response.status_code == 502
    assert response.json()["error"]["details"] == {"failure_code": code}
    assert po(session, order["id"]).status == "APPROVED"
    assert [(row.result, row.failure_code) for row in rows(session, order["id"])] == [("FAILED", code)]
    assert len(calls) == len(errors) == 1  # 요청당 한 번만 전송하고 한 번만 기록한다
    assert all(FAKE_KEY not in value for value in (response.text, caplog.text, errors[0], all_values(session, order["id"])))


def test_resend_supplier_bodies_exclude_internal_values(doc, resend_http):  # noqa: F811
    calls = resend_http(200)
    msg = po_mail.build_message(doc, po_mail.default_intro(doc), "staff@scm.test")
    po_mail.deliver(msg)

    payload, = calls
    for part in ("subject", "text", "html"):
        assert all(value not in payload[part] for value in SECRETS + INTERNAL_IDS)
    assert MEMO in payload["text"] and MEMO in payload["html"]


def test_admin_login_uses_resend_without_smtp(client, session, world, resend_http):
    calls = resend_http(200)
    world["a_admin"].otp_grace_until = None
    session.commit()

    response = login(client)
    assert response.status_code == 200 and response.json()["data"]["otp_required"] is True
    payload, = calls
    assert payload["from"] == FROM and payload["to"] == [ADMIN]
    assert "html" not in payload and "attachments" not in payload
    code = re.search(r"\b([0-9]{6})\b", payload["text"]).group(1)
    assert verify(client, code).status_code == 200


def test_settings_rejects_unknown_mail_provider(monkeypatch):
    monkeypatch.setenv("MAIL_PROVIDER", "unsupported")
    with pytest.raises(ValidationError, match="mail_provider"):
        Settings(**GOOD, _env_file=None)


@pytest.mark.parametrize(("overrides", "missing"), [
    ({"resend_api_key": " "}, "RESEND_API_KEY"),
    ({"resend_from": ""}, "RESEND_FROM"),
])
def test_production_refuses_missing_resend_settings(overrides, missing):
    config = {**GOOD, "mail_provider": "resend", "smtp_host": "", "smtp_security": "none",
              "resend_api_key": FAKE_KEY, "resend_from": FROM}
    assert Settings(**config, _env_file=None).mail_provider == "resend"  # SMTP 설정 없이 시작한다
    for otp_enabled in (True, False):  # Resend 필수값은 OTP 스위치와 무관하다
        with pytest.raises(ValidationError, match=missing) as error:
            Settings(**{**config, **overrides, "admin_otp_enabled": otp_enabled}, _env_file=None)
        assert FAKE_KEY not in str(error.value) and FAKE_KEY not in repr(error.value)
