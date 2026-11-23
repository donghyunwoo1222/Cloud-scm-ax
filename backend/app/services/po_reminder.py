"""납기 지연 독촉 메일 (#269): 미리보기(GET) → 담당자가 읽고 확인 → 발송(POST). 자동·예약 발송 경로는 없다.

- 초안은 저장하지 않는다. 누를 때마다 지금 DB 값으로 같은 틀(build_reminder, 순수 함수)을 채운다.
- 발주서 상태·emailed_*(마지막 발주서 발송)·변경 이력은 바꾸지 않는다. 기록은 po_email_log(kind REMINDER) 시도마다 1행.
- 지연 판단은 purchase_orders.receipt_due_condition("OVERDUE") 한 곳(대시보드·목록과 같은 조건). 발송은 잠근 뒤 다시 본다.
- 한도(간격·발주당 횟수·회사 하루)는 발주서 행을 잠근 안에서 po_email_log 를 센다. 회사 행은 잠그지 않는다:
  SMTP 를 기다리는 최대 10초 동안 그 회사의 발주 작성·추천 초안(둘 다 회사 행을 잠근다)이 멈추기 때문이다.
  그래서 회사 하루 상한은 느슨하다(서로 다른 발주에 동시에 보내면 상한을 조금 넘을 수 있다).
- 메일 본문에 넣는 칸은 reminder_facts 가 고른 칸뿐이다(허용 목록, 문서: supplier-document-fields.md 6절).
  단가·금액·메모·지불조건·첨부는 넣지 않는다.
"""

import secrets  # 공급업체 링크 토큰 (발주서 메일과 같은 방식)
import smtplib  # 메일 서버 오류 종류
from datetime import datetime, time, timedelta  # 회사 하루의 시작, 간격, 링크 유효 기간
from email.message import EmailMessage  # 표준 메일 만들기
from email.utils import formataddr  # "회사명 <주소>" 모양
from html import escape  # 사용자·DB 글자를 HTML 에 넣기 전에 < > & 를 바꾼다

from sqlalchemy import and_, func, or_, select  # 조건, DB 현재 시각·집계, SELECT
from sqlalchemy.orm import Session  # DB 세션 타입

from app.auth.security import hash_reset_token  # 토큰 → SHA-256 해시 (원본은 저장하지 않는다)
from app.clock import SEOUL, seoul_today  # 서울 기준 날짜
from app.config import settings  # 스위치·한도·SMTP 설정
from app.errors import AppError  # 공통 오류
from app.models import Company, PoEmailLog, PurchaseOrder, Supplier, User  # 표들
from app.services import (
    po_mail,  # deliver·실패 코드·링크 규칙 재사용 (테스트는 po_mail.deliver 를 바꿔 끼운다)
)
from app.services import (
    purchase_orders as po_service,  # 지연 판단(overdue_order_ids)·줄 응답(build_out)
)
from app.services.po_change_log import text_of  # 날짜 → 글자
from app.services.po_states import ACTION_STATES, STATUS_NAMES  # 독촉할 수 있는 상태, 상태 이름
from app.services.tenant import get_owned  # 회사 분리 (다른 회사 404)

FAILED_TAIL = "발주서는 바뀌지 않았습니다."  # 실패 문장의 끝 (발주서 메일은 "승인됨 상태 그대로")
OLD_LINK_NOTE = "이전 메일의 링크는 더 이상 쓸 수 없으니 이 메일의 링크를 사용해 주세요."  # 새 토큰을 넣을 때만
# 한도에 세는 시도: 성공, 메일은 나갔으나 저장 실패, 시간 초과 실패(실제로는 도착했을 수 있다). 다른 실패는 세지 않는다
COUNTED = or_(PoEmailLog.result.in_(("SENT", "UNSAVED")),
              and_(PoEmailLog.result == "FAILED", PoEmailLog.failure_code == "TIMEOUT"))
FACT_KEYS = ("buyer_name", "supplier_name", "contact_name", "po_number", "order_date", "due_date",
             "supplier_due_date", "lines", "sender_name")  # 본문 허용 칸 (test_po_reminder_leak 이 고정)
LINE_KEYS = ("label", "remaining", "unit", "boxes")  # 품목 한 줄의 허용 칸


def check_order(company_id: int, db: Session, order_id: int, lock: bool) -> PurchaseOrder:
    """독촉할 수 있는 발주서인지: 404 → 스위치 503 → 상태 409 → 지연 409. lock=True 면 발주서 행을 잠근 뒤 본다."""
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=lock)  # 다른 회사·없는 id 는 404
    if not settings.po_reminder_enabled:
        raise AppError(503, "REMINDER_DISABLED", "독촉 메일 기능이 꺼져 있습니다. 관리자에게 문의하세요.")
    if order.status not in ACTION_STATES["remind"]:  # 작성 중·승인됨·입고 완료(잔량 마감 포함)·취소
        raise AppError(409, "INVALID_STATUS", f"{STATUS_NAMES[order.status]} 상태의 발주서는 독촉 메일을 보낼 수 없습니다. "
                       "발주함 상태이고 납기가 지난 발주만 보낼 수 있습니다.", {"status": order.status})
    if order.id not in po_service.overdue_order_ids(company_id, db, [order.id]):  # 지연 기준은 이 조건 한 곳
        details = ({"reason": "NO_DUE_DATE"} if order.due_date is None and order.supplier_due_date is None
                   else {"due_date": text_of(order.due_date), "supplier_due_date": text_of(order.supplier_due_date)})
        raise AppError(409, "NOT_OVERDUE", "납기가 아직 지나지 않았거나 납기일이 없는 발주서는 독촉 메일을 보낼 수 없습니다.", details)
    return order


def reminder_facts(company_id: int, db: Session, order: PurchaseOrder, sender: User) -> dict:
    """본문에 넣을 값만 고른다(허용 목록). 남은 수량이 있는 줄만. 남은 줄이 없으면 409 NOT_OVERDUE(NOTHING_REMAINING)."""
    out = po_service.build_out(company_id, db, [order])[0]  # 줄·누적 입고량 (발주 상세와 같은 계산)
    lines = []
    for i in out["items"]:
        remaining = i["quantity"] - i["received_quantity"]  # 재고 단위(낱개) 남은 수량
        if remaining <= 0:
            continue
        per_box = i["units_per_box"]  # 박스 발주 줄이면 1박스의 낱개 수
        lines.append({
            "label": f"{i['product_name']} ({i['product_sku']})",  # 발주서 메일과 같은 품목 표기
            "remaining": remaining,
            "unit": i["unit"],
            # 박스로 나누어떨어질 때만 박스 수를 함께 적는다. 예) 30개 남음, 1박스=10개 → 3 / 35개 → None
            "boxes": (remaining // per_box, i["order_unit"]) if per_box and remaining % per_box == 0 else None,
        })
    if not lines:  # 발주함이면 보통 남은 줄이 있다(다 차면 입고 완료가 된다). 안전망
        raise AppError(409, "NOT_OVERDUE", "아직 도착하지 않은 품목이 없어 독촉 메일을 보낼 수 없습니다.", {"reason": "NOTHING_REMAINING"})
    supplier = db.get_one(Supplier, order.supplier_id)  # 발주서와 같은 회사 업체 (작성 때 검사)
    return {
        "buyer_name": db.get_one(Company, company_id).name,  # 지금 회사 이름 (발주서 메일 제목과 같은 값)
        "supplier_name": supplier.name,
        "contact_name": supplier.contact_name,
        "po_number": order.po_number,
        "order_date": order.created_at.astimezone(SEOUL).date().isoformat(),  # 발주일 = 작성일 (문서와 같은 계산)
        "due_date": text_of(order.due_date),  # 약속 납기
        "supplier_due_date": text_of(order.supplier_due_date),  # 회신 납기 (없으면 None)
        "lines": lines,
        "sender_name": sender.name,  # 답장 받을 담당자 = 보내는 사람 (Reply-To 와 같은 사람)
    }


def build_reminder(facts: dict, link: str | None) -> dict:
    """독촉 메일의 제목·기본 앞머리·고정 부분(HTML·글자). DB 를 읽지 않는 순수 함수: 미리보기와 발송이 같은 글자를 쓴다.

    link: None 이면 링크 문단 없음, po_mail.LINK_PREVIEW 면 미리보기 문구, 그 밖은 실제 링크(+ 이전 링크 무효 안내)."""
    f = facts
    due = f["supplier_due_date"] or f["due_date"]  # 제목·앞머리에 보일 기준 납기 (지연 판단은 서버 조건이 이미 했다)
    who = f"{f['supplier_name']} {f['contact_name']}님" if f["contact_name"] else f"{f['supplier_name']} 담당자님"

    def qty(line: dict) -> str:  # 예) "30개 (= 3박스)", "35개"
        boxes = f" (= {line['boxes'][0]:,}{line['boxes'][1]})" if line["boxes"] else ""
        return f"{line['remaining']:,}{line['unit']}{boxes}"

    cell = "border:1px solid #999;padding:4px 8px"  # 칸마다 직접 적는다 (메일 프로그램은 <style> 을 자주 버린다)
    rows = "".join(f"<tr><td style='{cell}'>{escape(line['label'])}</td><td style='{cell};text-align:right'>{escape(qty(line))}</td></tr>"
                   for line in f["lines"])
    head = "".join(f"<th style='{cell};background:#eef5e4'>{h}</th>" for h in ("품목명 (SKU)", "남은 수량"))
    reply = f"<br>회신 납기 : {escape(f['supplier_due_date'])}" if f["supplier_due_date"] else ""
    note = f"<p>{OLD_LINK_NOTE}</p>" if link and link != po_mail.LINK_PREVIEW else ""
    fixed_html = (
        f"<p><b>발주번호 {escape(f['po_number'])}</b> · 발주일자 {escape(f['order_date'])}<br>"
        f"약속 납기 : {escape(f['due_date'] or '-')}{reply}</p>"
        f"<p><b>아직 도착하지 않은 품목</b></p>"
        f"<table style='border-collapse:collapse;font-size:14px'><tr>{head}</tr>{rows}</table>"
        f"{po_mail.link_html(link) + note if link else ''}"
        f"<p>이 메일에 답장하시면 {escape(f['sender_name'])} 담당자에게 전달됩니다.</p>"
    )
    lines = "\n".join(f"- {po_mail.flat(line['label'])}: {qty(line)}" for line in f["lines"])
    fixed_text = (
        f"발주번호 {f['po_number']} · 발주일자 {f['order_date']}\n"
        f"약속 납기: {f['due_date'] or '-'}\n" + (f"회신 납기: {f['supplier_due_date']}\n" if f["supplier_due_date"] else "")
        + f"\n아직 도착하지 않은 품목\n{lines}\n\n"
        + (po_mail.link_text(link) + (f"{OLD_LINK_NOTE}\n\n" if note else "") if link else "")
        + f"이 메일에 답장하시면 {po_mail.flat(f['sender_name'])} 담당자에게 전달됩니다."
    )
    return {
        "subject": f"[{f['buyer_name']}] 납기 확인 요청: 발주서 {f['po_number']} (납기 {due})",
        "intro": (f"{who}, 안녕하세요. {f['buyer_name']}입니다.\n"
                  f"아래 발주의 납기({due})가 지났는데 아직 도착하지 않은 품목이 있습니다. 도착 예정일을 알려 주시면 감사하겠습니다."),
        "fixed_html": fixed_html,
        "fixed_text": fixed_text,
    }


def counters(company_id: int, db: Session, order_id: int) -> dict:
    """이 발주의 독촉 횟수·마지막 시각·다음 가능 시각 (세는 기준은 COUNTED)."""
    count, last = db.execute(select(func.count(), func.max(PoEmailLog.created_at)).where(
        PoEmailLog.company_id == company_id, PoEmailLog.purchase_order_id == order_id,
        PoEmailLog.kind == "REMINDER", COUNTED)).one()  # 인덱스 ix_po_email_log_order
    return {
        "sent_count": count, "max_per_order": settings.po_reminder_max_per_order, "last_sent_at": last,
        "next_allowed_at": last + timedelta(hours=settings.po_reminder_interval_hours) if last else None,
    }


def limit_error(company_id: int, db: Session, c: dict) -> AppError | None:
    """한도에 걸리면 그 오류, 아니면 None. 순서: 발주당 횟수 → 간격 → 회사 하루. 시각은 DB 시각(created_at 과 같은 기준)."""
    if c["sent_count"] >= c["max_per_order"]:
        return AppError(409, "REMINDER_LIMIT", f"이 발주에는 독촉 메일을 이미 {c['sent_count']}번 보냈습니다. 더 보낼 수 없습니다.",
                        {"count": c["sent_count"], "limit": c["max_per_order"]})
    if c["next_allowed_at"] is not None and db.scalar(select(func.now())) < c["next_allowed_at"]:
        return AppError(409, "REMINDER_TOO_SOON", "마지막 독촉 뒤 아직 시간이 충분히 지나지 않았습니다. 다음 가능 시각 이후에 보내 주세요.",
                        {"next_allowed_at": c["next_allowed_at"].isoformat()})
    day_start = datetime.combine(seoul_today(), time.min, SEOUL)  # 서울 기준 오늘 0시
    today_count = db.scalar(select(func.count()).select_from(PoEmailLog).where(
        PoEmailLog.company_id == company_id, PoEmailLog.kind == "REMINDER", COUNTED, PoEmailLog.created_at >= day_start))
    if today_count >= settings.po_reminder_daily_per_company:
        return AppError(409, "REMINDER_DAILY_LIMIT", "오늘 보낼 수 있는 독촉 메일 수를 다 썼습니다. 내일 다시 보내 주세요.",
                        {"limit": settings.po_reminder_daily_per_company})
    return None


def build_preview(company_id: int, db: Session, user: User, order_id: int) -> dict:
    """GET /purchase-orders/{id}/reminder: 아무것도 바꾸지 않고 메일 서버에도 가지 않는다.

    이메일 없음·메일 설정 없음·한도는 오류 대신 칸으로 알려 화면이 이유를 보여 준다(발송 POST 가 실제로 막는다)."""
    order = check_order(company_id, db, order_id, lock=False)
    mail = build_reminder(reminder_facts(company_id, db, order, user), po_mail.LINK_PREVIEW if po_mail.supplier_link_base() else None)
    c = counters(company_id, db, order.id)
    blocked = limit_error(company_id, db, c)
    return {
        "to": db.get_one(Supplier, order.supplier_id).email,  # 비어 있으면 화면이 발송을 막고 안내한다
        "supplier_id": order.supplier_id,
        "reply_to": user.email,  # 답장 받을 주소 = 지금 보내는 사람
        "subject": mail["subject"], "intro": mail["intro"], "fixed_html": mail["fixed_html"],
        "with_link": po_mail.supplier_link_base() is not None,
        "mail_ready": bool(settings.smtp_host and settings.smtp_from),
        **c,
        "blocked": blocked.code if blocked else None,  # REMINDER_LIMIT / REMINDER_TOO_SOON / REMINDER_DAILY_LIMIT / None
    }


def build_message(facts: dict, intro: str, to: str, reply_to: str, link: str | None) -> EmailMessage:
    """보낼 메일 한 통: 시스템 주소에서 공급업체로, 답장은 보내는 담당자에게. 첨부 없음."""
    mail = build_reminder(facts, link)
    msg = EmailMessage()
    msg["Subject"] = mail["subject"]
    msg["From"] = formataddr((facts["buyer_name"], settings.smtp_from))  # 보내는 주소는 시스템 주소 하나, 이름만 회사명
    msg["To"] = to
    msg["Reply-To"] = reply_to
    msg.set_content(f"{intro}\n\n{mail['fixed_text']}")
    intro_html = escape(intro).replace("\n", "<br>")  # 사용자가 쓴 줄바꿈만 살리고 태그는 글자로 보이게
    msg.add_alternative(f"<div style='font-family:sans-serif'><p>{intro_html}</p>{mail['fixed_html']}</div>", subtype="html")
    return msg


def send_reminder(company_id: int, db: Session, user: User, order_id: int, intro: str) -> dict:
    """POST /purchase-orders/{id}/reminder. 발주서 잠금 → 검사 → 발송 → 이력 1행(커밋은 API).

    잠금 덕분에 같은 발주에 동시에 두 번 오면, 두 번째 요청은 첫 요청이 SENT 행을 커밋한 뒤에 그 행을 세어 409 REMINDER_TOO_SOON.
    발송 실패: 발주서·토큰은 하나도 바꾸지 않고 실패 이력 1행만 넣은 뒤 502. API 가 이 1행만 커밋한다.
    돌려주는 dict 는 이력 행 값이다. 커밋이 실패하면(MAIL_SENT_NOT_SAVED) API 가 이 값으로 UNSAVED 행을 남긴다.
    404·409·503 은 메일 서버에 가지 않았으므로 이력을 남기지 않는다.
    """
    order = check_order(company_id, db, order_id, lock=True)  # 잠금 (잠금 순서: 발주서 → 품목). 잠근 뒤 상태·지연을 다시 본다
    facts = reminder_facts(company_id, db, order, user)
    to = db.get_one(Supplier, order.supplier_id).email
    if not to:
        raise AppError(409, "NO_SUPPLIER_EMAIL", "공급업체 이메일이 없어 보낼 수 없습니다. 공급업체 정보에 이메일을 넣어 주세요.")
    if not (settings.smtp_host and settings.smtp_from):
        raise AppError(503, "MAIL_NOT_CONFIGURED", "메일 서버 설정이 없어 보낼 수 없습니다. 관리자에게 문의하세요.")
    if blocked := limit_error(company_id, db, counters(company_id, db, order.id)):  # 잠금 안에서 센다
        raise blocked
    base = po_mail.supplier_link_base()
    token = secrets.token_urlsafe(32) if base else None  # 원본 토큰은 메일 본문에만 들어간다 (DB·응답·로그에는 없음)
    link = f"{base}/supplier-reply#{token}" if token else None
    entry = {"company_id": company_id, "purchase_order_id": order.id, "kind": "REMINDER", "sent_by": user.id,
             "to_address": to, "with_link": token is not None}  # 이력 행 값 (토큰·본문·제목은 넣지 않는다)
    try:
        po_mail.deliver(build_message(facts, intro, to, user.email, link))  # 실제 발송 (최대 SMTP_TIMEOUT 초)
    except (smtplib.SMTPException, OSError) as exc:
        db.add(PoEmailLog(**entry, result="FAILED", failure_code=po_mail.failure_code(exc)))  # 여기까지 발주서는 그대로다
        raise po_mail.failure(exc, FAILED_TAIL) from exc
    if token:  # 발송이 성공한 뒤에만 새 토큰으로 덮어쓴다: 실패·저장 실패면 옛 링크가 그대로 유효하다
        order.supplier_token_hash = hash_reset_token(token)  # 해시만 저장 (옛 링크는 여기서 무효)
        order.supplier_token_expires_at = func.now() + timedelta(days=po_mail.LINK_DAYS)
    db.add(PoEmailLog(**entry, result="SENT"))  # 토큰과 같은 트랜잭션 (함께 저장되거나 함께 사라진다)
    db.flush()
    return entry
