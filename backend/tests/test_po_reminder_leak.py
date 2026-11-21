"""독촉 메일(#269)에 내부 정보가 새지 않는지: 단가·금액·메모·지불조건·납품장소·추천 사유·변경 이력·발송 이력·emailed_*·로그인 이메일.

본문 값은 po_reminder.reminder_facts 가 고른 칸(FACT_KEYS·LINE_KEYS)뿐이다(허용 목록, supplier-document-fields.md 6절).
test_supplier_doc_leak.py 의 ALLOWED_KEYS(발주서 문서 칸)는 바꾸지 않는다: 독촉은 build_document 를 쓰지 않는다.
"""

from sqlalchemy import select  # 조회

from app.models import PoEmailLog, PurchaseOrder, PurchaseOrderItem, User  # 표식을 넣을 표
from app.services import po_reminder  # 대상
from tests.test_po_reminder import URL, html, outbox, overdue, plain  # noqa: F401  (outbox 는 pytest 픽스처)

MEMO = "INTERNAL-MEMO-269"
TERMS = "INTERNAL-TERMS-269"
PLACE = "INTERNAL-PLACE-269"
REASON = "INTERNAL-REASON-269"
EMAILED = "internal-emailed-269@internal.test"
LOGGED = "internal-log-269@internal.test"
MARKERS = (MEMO, TERMS, PLACE, REASON, EMAILED, LOGGED, "admin@a.test", "6,500", "6500", "8,000", "8000", "440,000")  # 단가·금액 포함


def test_reminder_outputs_have_no_internal_values(client, session, world, outbox):  # noqa: F811
    order = overdue(client, session, world)
    po = session.get(PurchaseOrder, order["id"])
    po.memo, po.payment_terms, po.delivery_address, po.emailed_to = MEMO, TERMS, PLACE, EMAILED
    for item in session.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po.id)):
        item.recommendation_reason = REASON
    session.add(PoEmailLog(company_id=po.company_id, purchase_order_id=po.id, kind="ORDER", sent_by=world["a_admin"].id,
                           to_address=LOGGED, result="SENT", with_link=False))  # 이전 발송 이력
    session.commit()  # 변경 이력(po_change_log)은 reminder_facts 가 읽지 않는다 (FACT_KEYS 고정으로 확인)

    data = client.get(f"{URL}/{order['id']}/reminder").json()["data"]
    assert client.post(f"{URL}/{order['id']}/reminder", json={"intro": "확인 부탁드립니다."}).status_code == 200
    [msg] = outbox
    outputs = {"subject": msg["Subject"], "plain": plain(msg), "html": html(msg),
               "preview": data["subject"] + data["intro"] + data["fixed_html"]}
    for where, text in outputs.items():
        for marker in MARKERS:
            assert marker not in text, (where, marker)
    assert not list(msg.iter_attachments())  # 가격이 든 PDF·엑셀을 다시 보내지 않는다
    assert msg["Reply-To"] == "admin@a.test"  # 로그인 이메일은 머리글 Reply-To 에만
    assert order["po_number"] in outputs["plain"] and "P1" in outputs["plain"]  # 공개 칸은 빠지지 않았다


def test_fact_keys_are_fixed(client, session, world, outbox):  # noqa: F811
    order = overdue(client, session, world)
    po = session.get(PurchaseOrder, order["id"])
    facts = po_reminder.reminder_facts(po.company_id, session, po, session.get(User, world["a_admin"].id))
    assert tuple(facts) == po_reminder.FACT_KEYS
    assert all(tuple(line) == po_reminder.LINE_KEYS for line in facts["lines"])
