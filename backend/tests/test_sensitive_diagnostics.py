import logging  # 테스트에서 경고 로그를 명시적으로 수집한다
import smtplib  # 메일 서버가 본문을 거부한 상황을 만든다

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.config import settings
from app.db import engine
from app.services import password_reset, po_mail


def test_order_mail_failure_logs_code_without_server_reply(caplog):
    reply = b"synthetic-mail-body-marker"  # 서버가 원본 메일 일부를 되돌려 보낸 상황
    with caplog.at_level(logging.WARNING, logger=po_mail.__name__):
        error = po_mail.failure(smtplib.SMTPDataError(554, reply))

    assert error.details == {"failure_code": "OTHER"}
    assert "메일 발송 실패: OTHER" in caplog.text
    assert reply.decode() not in caplog.text


def test_password_reset_mail_failure_omits_link_and_body(monkeypatch, caplog):
    token = "synthetic-reset-marker"
    monkeypatch.setattr(settings, "app_base_url", "https://scm.example.invalid")
    monkeypatch.setattr(settings, "mail_provider", "smtp")
    monkeypatch.setattr(settings, "smtp_from", "scm@example.invalid")

    def reject(msg):
        raise smtplib.SMTPDataError(554, msg.get_content().encode())

    monkeypatch.setattr(po_mail, "deliver", reject)
    with caplog.at_level(logging.WARNING, logger=password_reset.__name__):
        password_reset.send_reset_mail("test@example.invalid", token)

    assert "SMTPDataError" in caplog.text
    assert token not in caplog.text
    assert "비밀번호를 다시 정하려면" not in caplog.text


def test_database_error_omits_bound_parameters():
    marker = 482759  # 오류가 나도 예외에 표시되면 안 되는 가짜 전달값
    with engine.connect() as connection, pytest.raises(DBAPIError) as failure:
        connection.execute(text("SELECT CAST(:value AS integer) / 0"), {"value": marker})

    assert "division by zero" in str(failure.value)
    assert str(marker) not in str(failure.value)
