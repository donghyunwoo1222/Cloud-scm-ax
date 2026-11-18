"""발주서 메일 본문(#264 PR3): 머리 표·글자 도장·승인 줄. DB 없이 문서 dict 만 쓴다."""

import re  # 금지 태그 검사

from app.services import po_mail  # 대상 모듈
from tests.test_po_pdf import make_doc  # 문서 dict 만드는 공통 도구

EVIL = "A&B<주>"  # 태그·& 가 들어간 상호
ESCAPED = "A&amp;B&lt;주&gt;"


def test_names_are_escaped_everywhere():
    doc = make_doc(buyer=EVIL, approver=EVIL, supplier={"name": EVIL, "contact_name": EVIL})
    doc["buyer"]["author_name"] = EVIL
    html = po_mail.fixed_html(doc)
    assert EVIL not in html  # 날 글자는 하나도 없다
    # 수신처 상호·담당자, 발주처 상호·작성자, 도장 글자, 승인자 이름 = 최소 6곳
    assert html.count(ESCAPED) >= 6
    assert f"{ESCAPED} (인)" in html


def test_stamp_and_approval_in_html_and_text():
    doc = make_doc()
    html, text = po_mail.fixed_html(doc), po_mail.fixed_text(doc)
    for body in (html, text):
        for token in ("(인)", "전자 승인 표시", "박관리", "2026-11-18 09:30", "한빛생활용품"):
            assert token in body
    assert "한빛생활용품 (인)" in html and "color:#c62828" in html and "border:2px solid #c62828" in html
    assert "발주처: 한빛생활용품 (인)" in text
    assert "승인: 박관리 · 2026-11-18 09:30 (전자 승인 표시)" in text


def test_empty_approval_shows_dash():
    doc = make_doc(approver=None, at=None)
    assert "승인 : - · - (전자 승인 표시)" in po_mail.fixed_html(doc)
    assert "승인: - · - (전자 승인 표시)" in po_mail.fixed_text(doc)


def test_changed_company_name_line_only_when_different():
    same, changed = make_doc(), make_doc(buyer="새상호", company="옛상호")
    for fn in (po_mail.fixed_html, po_mail.fixed_text):
        assert "승인 시점 상호" not in fn(same)
        assert "(승인 시점 상호 : 옛상호)" in fn(changed)
    assert "옛상호 (인)" in po_mail.fixed_html(changed)  # 도장은 승인 시점 상호


def test_html_has_no_forbidden_markup():
    html = po_mail.fixed_html(make_doc(buyer=EVIL))
    assert not re.search(r"<script|<svg|<img|class=", html, re.IGNORECASE)


def test_header_table_has_every_field():
    doc = make_doc()
    html, text = po_mail.fixed_html(doc), po_mail.fixed_text(doc)
    for value in ("대한물산", "김대한", "02-111-2222", "a@b.kr", "한빛생활용품", "123-45-67890", "홍길동",
                  "031-000-1111", "경기도 성남시 1-2", "이수진"):
        assert value in html and value in text
    assert "수신처" in html and "발주처" in html


def test_empty_header_fields_become_dash_and_memo_is_public():
    doc = make_doc(supplier={"phone": None, "email": None})
    doc["buyer"]["representative"] = None
    html, text = po_mail.fixed_html(doc), po_mail.fixed_text(doc)
    assert "연락처 : -" in html and "대표자 : -" in html and "이메일 : -" in html
    assert "대표자: -" in text and "이메일: -" in text
    assert "포장 주의" in html and "포장 주의" in text  # memo 는 공개 칸


def test_newlines_in_values_do_not_break_text_body():
    doc = make_doc(buyer="한빛\n승인: 가짜 · 가짜")
    doc["buyer"]["address"] = "서울\r\n발주번호 PO-FAKE"
    text = po_mail.fixed_text(doc)
    assert text.count("\n승인: ") == 1  # 값 안의 줄바꿈으로 가짜 승인 줄이 생기지 않는다
    assert "\nPO-FAKE" not in text and "\n발주번호 PO-FAKE" not in text


def test_subject_and_attachment_names_unchanged():
    doc = make_doc()
    assert po_mail.subject_of(doc) == "[한빛생활용품] 발주서 PO-20261118-001 (2026-11-18)"
