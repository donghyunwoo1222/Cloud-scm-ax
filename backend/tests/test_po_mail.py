"""발주서 메일 반자동 발송(#158): 가짜 메일 서버로 성공·실패·상태·권한·회사 분리·다시 보내기."""

import smtplib  # 실패를 흉내 낼 SMTP 오류

import pytest  # 테스트 도구

from app.config import settings  # SMTP 설정 (테스트 동안만 바꾼다)
from app.services import po_mail  # 바꿔 끼울 발송 함수
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_document import make_order  # 발주서 준비 도구 (#157)

URL = "/api/v1/purchase-orders"  # 발주 경로
INTRO = "안녕하세요.\n<b>발주</b> 드립니다."  # 사용자가 고친 앞머리 (태그는 글자로 나가야 한다)


@pytest.fixture
def outbox(monkeypatch):
    """가짜 메일 서버: 실제로 보내지 않고 보낸 메일을 목록에 담는다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")  # 설정이 있는 것처럼
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(po_mail, "deliver", sent.append)  # 발송 = 목록에 담기
    return sent


def with_email(session, world, email="sales@a-supplier.test"):
    world["a_supplier"].email = email
    session.commit()


def test_send_success_orders_and_records(client, session, world, outbox):
    with_email(session, world)
    order, _ = make_order(client, session, world)
    doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
    response = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO})
    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    # 성공하면 ORDERED + 기록 3칸
    assert data["status"] == "ORDERED" and data["ordered_at"] and data["emailed_at"]
    assert data["emailed_to"] == "sales@a-supplier.test" and data["emailed_by"] == world["a_admin"].id
    [msg] = outbox
    assert msg["To"] == "sales@a-supplier.test" and msg["Reply-To"] == "admin@a.test"  # 답장은 보낸 담당자에게
    assert "noreply@scm.test" in msg["From"]  # 보내는 주소는 시스템 주소 하나
    assert msg["Subject"] == f"[회사A] 발주서 {order['po_number']} ({doc['order_date']})"
    names = [part.get_filename() for part in msg.iter_attachments()]
    assert names == [f"{order['po_number']}.pdf", f"{order['po_number']}.xlsx"]
    pdf = next(msg.iter_attachments()).get_content()
    assert pdf.startswith(b"%PDF")  # 진짜 PDF
    html = msg.get_body(("html",)).get_content()
    assert "&lt;b&gt;발주&lt;/b&gt;" in html and "<b>발주</b>" not in html  # 사용자 글자는 태그로 해석되지 않는다
    assert f"{doc['total']:,}" in html and doc["total_korean"] in html  # 화면과 같은 합계


def test_send_failure_keeps_approved(client, session, world, outbox, monkeypatch):
    with_email(session, world)
    order, _ = make_order(client, session, world)

    def broken(msg):
        raise smtplib.SMTPServerDisconnected("down")

    monkeypatch.setattr(po_mail, "deliver", broken)
    response = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO})
    assert response.status_code == 502 and response.json()["error"]["code"] == "MAIL_FAILED"
    after = client.get(f"{URL}/{order['id']}").json()["data"]
    assert after["status"] == "APPROVED" and after["emailed_at"] is None and after["ordered_at"] is None


def test_no_supplier_email_blocks(client, session, world, outbox):
    order, _ = make_order(client, session, world)  # 공급업체 이메일 없음
    preview = client.get(f"{URL}/{order['id']}/email").json()["data"]
    assert preview["to"] is None and preview["supplier_id"] == world["a_supplier"].id  # 미리보기는 열리고 화면이 안내한다
    response = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO})
    assert response.status_code == 409 and response.json()["error"]["code"] == "NO_SUPPLIER_EMAIL"
    assert outbox == []


def test_only_approved_or_ordered(client, session, world, outbox):
    with_email(session, world)
    order, _ = make_order(client, session, world, approve=False)  # DRAFT
    assert client.get(f"{URL}/{order['id']}/email").status_code == 409
    assert client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO}).status_code == 409
    client.post(f"{URL}/{order['id']}/approve")
    client.post(f"{URL}/{order['id']}/cancel")  # CANCELLED
    assert client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO}).status_code == 409
    assert outbox == []


def test_resend_needs_confirmation_and_keeps_last(client, session, world, outbox):
    with_email(session, world)
    order, _ = make_order(client, session, world)
    first = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO}).json()["data"]
    # 더블클릭처럼 같은 요청이 한 번 더 오면 막힌다 (resend 없이)
    again = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO})
    assert again.status_code == 409 and again.json()["error"]["code"] == "ALREADY_ORDERED"
    assert len(outbox) == 1
    # 공급업체 이메일을 바꾸고 확인 후 다시 보내면 기록은 마지막 1건으로 덮인다
    with_email(session, world, "new@a-supplier.test")
    login_as(client, "staff@a.test")  # 담당자도 보낼 수 있다
    resent = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO, "resend": True}).json()["data"]
    assert resent["status"] == "ORDERED" and resent["emailed_to"] == "new@a-supplier.test"
    assert resent["emailed_by"] == world["a_staff"].id and resent["ordered_at"] == first["ordered_at"]  # 발주함 시각은 그대로
    assert len(outbox) == 2


def test_other_company_and_body_rules(client, session, world, outbox):
    with_email(session, world)
    order, _ = make_order(client, session, world)
    login_as(client, "admin@b.test")
    assert client.get(f"{URL}/{order['id']}/email").status_code == 404  # 다른 회사 발주서는 보이지도 않는다
    assert client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO}).status_code == 404
    login_as(client, "admin@a.test")
    assert client.post(f"{URL}/{order['id']}/email", json={"intro": ""}).status_code == 422  # 빈 앞머리
    bad = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO, "to": "evil@x.test"})
    assert bad.status_code == 422  # 받는 주소는 본문으로 바꿀 수 없다
    assert outbox == []


def test_not_configured(client, session, world, monkeypatch):
    with_email(session, world)
    monkeypatch.setattr(settings, "smtp_host", "")  # 메일 서버 설정 없음
    order, _ = make_order(client, session, world)
    assert client.get(f"{URL}/{order['id']}/email").json()["data"]["mail_ready"] is False
    response = client.post(f"{URL}/{order['id']}/email", json={"intro": INTRO})
    assert response.status_code == 503 and response.json()["error"]["code"] == "MAIL_NOT_CONFIGURED"
    assert client.get(f"{URL}/{order['id']}").json()["data"]["status"] == "APPROVED"
