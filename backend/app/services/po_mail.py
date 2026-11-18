"""발주서 메일 반자동 발송(#158): 미리보기 → 확인 → SMTP 발송 → 성공하면 ORDERED + 발송 기록.

메일 문장은 고정 틀이다(LLM 아님). 사용자는 앞머리 한 문단(intro)만 고친다. 숫자는 발주서 문서(build_document)와 같은 값을 쓴다.
"""

import smtplib  # 표준 SMTP 클라이언트 (새 라이브러리 없음)
from email.message import EmailMessage  # 표준 메일 만들기 (본문·첨부·머리글)
from email.utils import formataddr  # "회사명 <주소>" 모양 만들기
from html import (
    escape,  # 사용자·DB 글자를 HTML 에 넣기 전에 < > & 를 바꾼다 (본문에 태그가 끼어들지 않게)
)

from sqlalchemy import func  # DB 의 현재 시각
from sqlalchemy.orm import Session  # DB 세션 타입

from app.config import settings  # SMTP 설정 (환경 변수)
from app.errors import AppError  # 공통 오류
from app.models import PurchaseOrder, User  # 표들
from app.services import po_document  # 문서 값·PDF·엑셀
from app.services import purchase_orders as po_service  # 상태 변경 함수 set_status (#260)
from app.services.po_states import ACTION_STATES  # 보낼 수 있는 상태 (#260)
from app.services.tenant import get_owned  # 회사 조건이 붙은 조회 (다른 회사 404)

SMTP_TIMEOUT = 10  # 메일 서버 응답을 기다리는 최대 초 (그동안 발주서 행이 잠겨 있다)
INTRO_MAX = 2000  # 앞머리 문단 최대 글자 수 (스키마와 같은 값)


def default_intro(doc: dict) -> str:
    """앞머리 기본 문단. 미리보기에서 사용자가 고칠 수 있다."""
    s = doc["supplier"]
    who = f"{s['name']} {s['contact_name']}님" if s["contact_name"] else f"{s['name']} 담당자님"  # 담당자 이름이 없으면 "담당자님"
    return (f"{who}, 안녕하세요. {doc['buyer']['name']}입니다.\n"
            f"아래와 같이 발주드리니 확인 부탁드립니다. 발주서(PDF·엑셀)를 첨부합니다.")


def subject_of(doc: dict) -> str:
    """제목: [회사명] 발주서 PO-… (발주일자)."""
    return f"[{doc['buyer']['name']}] 발주서 {doc['po_number']} ({doc['order_date']})"


def dash(value) -> str:
    """빈 칸은 "-" (HTML 용: 글자를 escape 한다)."""
    return escape(str(value)) if value else "-"


def flat(value) -> str:
    """글자 본문용: 줄바꿈·연속 공백을 한 칸으로 접고 비면 "-" (값 안의 줄바꿈이 본문 줄 구조를 깨지 않게)."""
    return " ".join(str(value or "").split()) or "-"


def party_rows(doc: dict) -> tuple[list, list]:
    """머리 표 두 칸의 (라벨, 값) 목록: 수신처(공급업체) / 발주처(우리 회사). HTML·글자 본문이 같은 목록을 쓴다."""
    s, b = doc["supplier"], doc["buyer"]
    return (
        [("상호", s["name"]), ("담당자", s["contact_name"]), ("연락처", s["phone"]), ("이메일", s["email"])],
        [("상호", b["name"]), ("사업자번호", po_document.fmt_business_number(b["business_number"])), ("대표자", b["representative"]),
         ("연락처", b["phone"]), ("주소", b["address"]), ("작성자", b["author_name"])],
    )


def fixed_html(doc: dict) -> str:
    """앞머리 아래 고정 부분(품목표·합계·납기·납품장소·지불조건). 미리보기와 실제 메일이 이 글자를 똑같이 쓴다."""
    cell = "border:1px solid #999;padding:4px 8px"  # 칸 테두리·여백 (메일 프로그램은 <style> 을 자주 버려 칸마다 직접 적는다)
    num = cell + ";text-align:right"  # 숫자 칸은 오른쪽 정렬
    rows = "".join(
        f"<tr><td style='{cell};text-align:center'>{line['no']}</td>"
        f"<td style='{cell}'>{escape(line['product_name'])} ({escape(line['product_sku'])})</td>"
        f"<td style='{cell};text-align:center'>{escape(line['unit'])}</td>"
        f"<td style='{num}'>{line['quantity']:,}</td><td style='{num}'>{line['unit_price']:,}</td>"
        f"<td style='{num}'>{line['amount']:,}</td><td style='{cell}'>{escape(line['note'])}</td></tr>"
        for line in doc["lines"]
    )
    totals = "".join(
        f"<tr><th colspan='5' style='{cell};background:#eef5e4'>{label}</th><td colspan='2' style='{num}'>{value:,}</td></tr>"
        for label, value in (("공급가액 합계", doc["supply_total"]), ("부가세 (10%)", doc["vat"]), ("합계", doc["total"]))
    )
    head = "".join(f"<th style='{cell};background:#eef5e4'>{h}</th>" for h in ("No.", "품목명 (SKU)", "단위", "수량", "단가", "공급가액", "비고"))
    conditions = "".join(
        f"<li>{label} : {escape(value or '')}</li>"
        for label, value in (("납기일자", doc["due_date"]), ("납품장소", doc["delivery_address"]),
                             ("지불조건", doc["payment_terms"]), ("기타", doc["memo"]))
    )
    box = f"vertical-align:top;width:50%;{cell}"  # 머리 표 한 칸 (table·인라인 style 만: 메일 프로그램 호환)
    parties = "".join(
        f"<td style='{box}'><b>{title}</b><br>" + "<br>".join(f"{label} : {dash(value)}" for label, value in rows) + "</td>"
        for title, rows in zip(("수신처", "발주처"), party_rows(doc), strict=True)
    )
    ap = doc["approval"]  # 승인 기록: 이름·시각이 없으면 "-"
    changed = (f"<br>(승인 시점 상호 : {escape(ap['company_name'])})"  # 승인 뒤 상호가 바뀐 경우에만 한 줄 더 (PDF 와 같은 조건)
               if ap["company_name"] != doc["buyer"]["name"] else "")
    stamp = ("<span style='display:inline-block;color:#c62828;border:2px solid #c62828;border-radius:8px;"
             f"padding:4px 12px;font-weight:bold'>{escape(ap['company_name'])} (인)</span>")  # 그림이 아니라 글자 도장 (이미지 차단 대비)
    return (
        f"<table style='border-collapse:collapse;font-size:14px;width:100%'><tr>{parties}</tr></table>"
        f"<p><b>발주번호 {escape(doc['po_number'])}</b> · 발주일자 {doc['order_date']}<br>"
        f"합계금액 : 일금 {doc['total_korean']} 원정 (₩{doc['total']:,}, 부가세 포함)</p>"
        f"<table style='border-collapse:collapse;font-size:14px'><tr>{head}</tr>{rows}{totals}</table>"
        f"<p><b>발주 조건</b></p><ul>{conditions}</ul>"
        f"<p>위와 같이 발주합니다.</p><p>{stamp}</p>"
        f"<p>승인 : {dash(ap['approver_name'])} · {dash(ap['approved_at'])} (전자 승인 표시){changed}</p>"
        f"<p>이 메일에 답장하시면 {escape(doc['buyer']['author_name'])} 담당자에게 전달됩니다.</p>"
    )


def fixed_text(doc: dict) -> str:
    """HTML 을 못 보는 메일 프로그램용 글자 본문 (같은 값)."""
    lines = "\n".join(
        f"{line['no']}. {line['product_name']} ({line['product_sku']}) {line['quantity']:,}{line['unit']} × "
        f"{line['unit_price']:,} = {line['amount']:,}원 {line['note']}".rstrip()
        for line in doc["lines"]
    )
    ap = doc["approval"]
    changed = f"\n(승인 시점 상호 : {flat(ap['company_name'])})" if ap["company_name"] != doc["buyer"]["name"] else ""
    parties = "\n\n".join(
        f"[{title}]\n" + "\n".join(f"{label}: {flat(value)}" for label, value in rows)
        for title, rows in zip(("수신처", "발주처"), party_rows(doc), strict=True)
    )
    return (
        f"{parties}\n\n"
        f"발주번호 {doc['po_number']} · 발주일자 {doc['order_date']}\n\n{lines}\n\n"
        f"공급가액 합계 {doc['supply_total']:,}원 / 부가세 {doc['vat']:,}원 / 합계 {doc['total']:,}원 (일금 {doc['total_korean']} 원정)\n\n"
        f"납기일자: {doc['due_date'] or ''}\n납품장소: {doc['delivery_address'] or ''}\n"
        f"지불조건: {doc['payment_terms'] or ''}\n기타: {doc['memo'] or ''}\n\n"
        f"위와 같이 발주합니다.\n발주처: {flat(ap['company_name'])} (인)\n"
        f"승인: {flat(ap['approver_name'])} · {flat(ap['approved_at'])} (전자 승인 표시){changed}\n\n"
        f"이 메일에 답장하시면 {doc['buyer']['author_name']} 담당자에게 전달됩니다."
    )


def load_mail_document(company_id: int, db: Session, order: PurchaseOrder) -> dict:
    """보낼 수 있는 상태인지 보고 문서 값을 만든다. DRAFT·RECEIVED·CANCELLED 는 409."""
    if order.status not in ACTION_STATES["email"]:  # 승인됨(첫 발송) · 발주함(다시 보내기)
        raise AppError(409, "INVALID_STATUS", "승인됨·발주함 상태의 발주서만 메일로 보낼 수 있습니다.", {"status": order.status})
    return po_document.build_document(company_id, db, order.id)


def build_preview(company_id: int, db: Session, user: User, order_id: int) -> dict:
    """GET /purchase-orders/{id}/email: 받는 사람·제목·기본 앞머리·고정 부분. 이메일이 없어도 열린다(화면이 안내한다)."""
    order = get_owned(company_id, db, PurchaseOrder, order_id)  # 다른 회사·없는 id 는 404
    doc = load_mail_document(company_id, db, order)
    return {
        "to": doc["supplier"]["email"],  # 비어 있으면 화면이 발송을 막고 안내한다
        "supplier_id": order.supplier_id,  # 이메일 입력하러 갈 공급업체
        "reply_to": user.email,  # 답장 받을 주소 = 지금 보내는 사람
        "subject": subject_of(doc),
        "intro": default_intro(doc),
        "fixed_html": fixed_html(doc),
        "attachments": [f"{doc['po_number']}.pdf", f"{doc['po_number']}.xlsx"],
        "status": order.status,
        "emailed_at": order.emailed_at, "emailed_to": order.emailed_to,  # 이미 보냈으면 확인창에서 한 번 더 묻는다
        "mail_ready": bool(settings.smtp_host and settings.smtp_from),  # 메일 서버 설정이 없으면 화면이 미리 안내한다
    }


def build_message(doc: dict, intro: str, reply_to: str) -> EmailMessage:
    """보낼 메일 한 통: 시스템 주소에서 공급업체로, 답장은 담당자에게, PDF·엑셀 첨부."""
    msg = EmailMessage()
    msg["Subject"] = subject_of(doc)
    msg["From"] = formataddr((doc["buyer"]["name"], settings.smtp_from))  # 보내는 주소는 시스템 주소 하나, 이름만 회사명
    msg["To"] = doc["supplier"]["email"]
    msg["Reply-To"] = reply_to  # 공급업체가 답장하면 담당자 메일함으로 간다
    msg.set_content(f"{intro}\n\n{fixed_text(doc)}")  # 글자 본문
    intro_html = escape(intro).replace("\n", "<br>")  # 사용자가 쓴 줄바꿈만 살리고 태그는 글자로 보이게
    msg.add_alternative(f"<div style='font-family:sans-serif'><p>{intro_html}</p>{fixed_html(doc)}</div>", subtype="html")
    msg.add_attachment(po_document.build_pdf(doc), maintype="application", subtype="pdf", filename=f"{doc['po_number']}.pdf")
    msg.add_attachment(po_document.build_xlsx(doc), maintype="application",
                       subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename=f"{doc['po_number']}.xlsx")
    return msg


def deliver(msg: EmailMessage) -> None:
    """SMTP 로 실제 발송. 테스트는 이 함수를 가짜로 바꿔 끼운다(monkeypatch)."""
    smtp_class = smtplib.SMTP_SSL if settings.smtp_security == "ssl" else smtplib.SMTP  # 465 는 처음부터 암호화
    with smtp_class(settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT) as smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls()  # 587: 연결 뒤 암호화로 바꾼다 (비밀번호가 평문으로 가지 않게)
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def failure(exc: Exception) -> AppError:
    """발송 실패를 사용자가 알아들을 문장으로 (메일 서버의 원문 오류·비밀번호는 내보내지 않는다)."""
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        reason = "메일 서버 로그인에 실패했습니다. 관리자에게 메일 설정 확인을 요청하세요."
    elif isinstance(exc, smtplib.SMTPRecipientsRefused):
        reason = "메일 서버가 받는 주소를 거부했습니다. 공급업체 이메일을 확인하세요."
    else:
        reason = "메일 서버에 연결하지 못했거나 발송 중 오류가 났습니다. 잠시 뒤 다시 시도하세요."
    return AppError(502, "MAIL_FAILED", f"{reason} 발주서는 승인됨 상태 그대로입니다.", {"error": type(exc).__name__})


def send_order(company_id: int, db: Session, user: User, order_id: int, intro: str, resend: bool) -> PurchaseOrder:
    """POST /purchase-orders/{id}/email. 발주서 잠금 → 검사 → 발송 → 성공이면 ORDERED + 기록(커밋은 API).

    잠금 덕분에 더블클릭한 두 번째 요청은 첫 요청이 끝날 때까지 기다렸다가 ORDERED 를 보고 409 가 된다(resend 없이).
    실패하면 아무것도 바꾸지 않고 502 → 요청이 끝나며 되돌려져 APPROVED 그대로.
    """
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # 발주서 잠금 (잠금 순서: 회사 → 발주서 → 품목)
    doc = load_mail_document(company_id, db, order)  # DRAFT·RECEIVED·CANCELLED 409
    if order.status == "ORDERED" and not resend:  # 이미 발주함: 화면이 한 번 더 묻고 resend=true 로 보낸다
        raise AppError(409, "ALREADY_ORDERED", "이미 발주함 상태인 발주서입니다. 다시 보내려면 한 번 더 확인하세요.",
                       {"emailed_at": order.emailed_at.isoformat() if order.emailed_at else None, "emailed_to": order.emailed_to})
    to = doc["supplier"]["email"]
    if not to:
        raise AppError(409, "NO_SUPPLIER_EMAIL", "공급업체 이메일이 없어 보낼 수 없습니다. 공급업체 정보에 이메일을 넣어 주세요.")
    if not (settings.smtp_host and settings.smtp_from):
        raise AppError(503, "MAIL_NOT_CONFIGURED", "메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요.")
    try:
        deliver(build_message(doc, intro, user.email))  # 실제 발송 (최대 SMTP_TIMEOUT 초)
    except (smtplib.SMTPException, OSError) as exc:  # 메일 서버 거부·연결 실패·시간 초과
        raise failure(exc) from exc
    if order.status == "APPROVED":  # 첫 발송: 발주함으로 (주문 완료 표시와 같은 효과). 다시 보내기는 상태·이력 그대로
        po_service.set_status(db, company_id, order, user.id, "email")  # 이력 → ORDERED (#260)
        order.ordered_at = func.now()
    order.emailed_at, order.emailed_to, order.emailed_by = func.now(), to, user.id  # 마지막 1건만 남긴다 (다시 보내면 덮어씀)
    db.flush()
    db.refresh(order)  # func.now() 값을 실제 시각으로 다시 읽는다
    return order
