"""매입 세금계산서 수취 기록과 입고 금액 대조 (#268). 내부 전용: 발주서 응답(build_out)·공급업체 문서에는 넣지 않는다.

대조 = 받은 공급가액 합(취소 제외) − 입고 금액. 입고 금액은 원가 카드와 같은 cost_of(received_goods_krw) 한 곳에서 계산한다.
예) 1,000개 × 1,000원 중 600개 입고 → 입고 금액 600,000. 계산서 300,000 + 250,000 → 차이 −50,000(덜 받음) → DIFFERENT
"""

from datetime import UTC, datetime  # 취소 시각

from sqlalchemy.exc import IntegrityError  # 번호 유일 인덱스 위반 (동시 요청)
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import date_problem, oldest_allowed, seoul_today  # 입출고일과 같은 날짜 규칙
from app.errors import AppError  # 공통 오류
from app.models import PurchaseOrder, PurchaseOrderItem, PurchaseTaxInvoice  # 표
from app.schemas.purchase_orders import TaxInvoiceCreate  # 요청 모양
from app.services import purchase_orders as po_service  # 누적 입고량·원가(입고 기준) 계산 재사용
from app.services.export import user_names  # 사용자 id → 이름 (같은 회사만)
from app.services.po_document import (
    vat_of,  # 예상 세액 = 공급가액의 10% 원 미만 버림 (발주서 문서와 같은 규칙)
)
from app.services.po_states import STATUS_NAMES  # 오류 문장의 상태 이름
from app.services.tenant import get_owned, scoped  # 회사 분리 도우미

# 새 기록을 받을 수 있는 발주서 상태. po_states.ACTION_STATES 표는 기존 테스트가 키 목록을 고정해 두어 여기 둔다
RECORD_STATES = ("ORDERED", "RECEIVED")


def invoice_out(row: PurchaseTaxInvoice, names: dict[int, str]) -> dict:
    """계산서 한 장의 응답. 합계와 예상 세액은 저장하지 않고 여기서 계산한다."""
    return {
        "id": row.id, "invoice_number": row.invoice_number, "issue_date": row.issue_date.isoformat(),
        "supply_amount": row.supply_amount, "tax_amount": row.tax_amount,
        "total": row.supply_amount + row.tax_amount,  # 합계 (저장 안 함)
        "tax_expected": vat_of(row.supply_amount),  # 예상 세액. 다르면 화면이 안내만 한다 (저장은 막지 않음)
        "memo": row.memo,
        "created_by": row.created_by, "created_by_name": names.get(row.created_by),
        "created_at": row.created_at.isoformat(),
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "cancelled_by": row.cancelled_by, "cancelled_by_name": names.get(row.cancelled_by),
        "cancel_reason": row.cancel_reason,
    }


def view(company_id: int, db: Session, order: PurchaseOrder) -> dict:
    """GET 응답 {items, summary}. items 는 최신순(취소한 것 포함), summary 는 취소한 것을 뺀 합계로 대조한다."""
    rows = list(db.scalars(scoped(company_id, PurchaseTaxInvoice).where(
        PurchaseTaxInvoice.purchase_order_id == order.id).order_by(PurchaseTaxInvoice.id.desc())))
    lines = list(db.scalars(scoped(company_id, PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order.id)))
    received = po_service.received_quantities(company_id, db, [i.id for i in lines])  # 입고 − 정정 (줄별)
    received_krw = po_service.cost_of(order, lines, received).received_goods_krw or 0  # 발주함·입고 완료가 아니면 None → 0
    active = [r for r in rows if r.cancelled_at is None]
    supply_total = sum(r.supply_amount for r in active)
    difference = supply_total - received_krw  # + 더 받음, − 덜 받음
    if received_krw > 0 and not active:
        verdict = "MISSING"  # 입고는 됐는데 계산서가 한 장도 없다
    elif difference == 0:
        verdict = "MATCHED"
    else:
        verdict = "DIFFERENT"  # 차이는 표시만 하고 막지 않는다
    names = user_names(company_id, db, {r.created_by for r in rows} | {r.cancelled_by for r in rows})
    return {
        "items": [invoice_out(r, names) for r in rows],
        "summary": {
            "received_goods_krw": received_krw, "supply_total": supply_total,
            "tax_total": sum(r.tax_amount for r in active), "difference": difference, "status": verdict,  # 대조 결과 (발주서 status 와 다른 값)
            "line_count": sum(1 for i in lines if received.get(i.id, 0) > 0),  # 입고된 줄 수
        },
    }


def get_view(company_id: int, db: Session, order_id: int) -> dict:
    """GET /purchase-orders/{id}/tax-invoices. 다른 회사·없는 발주서는 404."""
    return view(company_id, db, get_owned(company_id, db, PurchaseOrder, order_id))


def record(company_id: int, db: Session, user_id: int, order_id: int, data: TaxInvoiceCreate) -> dict:
    """POST: 발주서를 잠근 뒤 상태 → 통화 → 날짜 순으로 검사하고 한 장 넣는다. 같은 업체의 유효한 같은 번호는 409."""
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # 404. 잠금은 커밋 때 풀린다
    if order.status not in RECORD_STATES:
        raise AppError(409, "INVALID_STATUS", f"{STATUS_NAMES[order.status]} 상태의 발주서에는 세금계산서를 기록할 수 없습니다.",
                       {"status": order.status})
    if order.currency != "KRW":  # 외화 부가세 기준은 보류(money-rules.md 10번)
        raise AppError(422, "VALIDATION_ERROR", "외화 발주서에는 세금계산서를 기록할 수 없습니다.",
                       [{"field": "currency", "reason": "unsupported"}])
    today = seoul_today()
    problem = date_problem(data.issue_date, today)  # 미래·5년보다 이른 날짜
    if problem is not None:
        message = "발행일은 오늘 이후로 할 수 없습니다." if problem == "FUTURE_DATE" else \
            f"발행일은 {oldest_allowed(today)}보다 이를 수 없습니다. 연도를 확인해 주세요."
        raise AppError(422, "VALIDATION_ERROR", message, [{"field": "issue_date", "reason": "invalid"}])
    row = PurchaseTaxInvoice(
        company_id=company_id, purchase_order_id=order.id, supplier_id=order.supplier_id,  # 업체는 발주서에서
        invoice_number=data.invoice_number, issue_date=data.issue_date,
        supply_amount=data.supply_amount, tax_amount=data.tax_amount, memo=data.memo or None, created_by=user_id,
    )
    try:
        with db.begin_nested():  # 세이브포인트: 번호가 겹치면 이 한 줄만 되돌리고 발주서 잠금은 유지
            db.add(row)
            db.flush()
    except IntegrityError as e:
        if getattr(e.orig.diag, "constraint_name", None) == "uq_purchase_tax_invoices_number":  # 동시 요청도 여기서 걸린다
            raise AppError(409, "DUPLICATE_TAX_INVOICE", "이 공급업체에 같은 번호의 세금계산서가 이미 기록되어 있습니다.",
                           [{"field": "invoice_number", "reason": "duplicate"}]) from None
        raise  # 그 밖의 위반은 예상 밖 (500)
    return view(company_id, db, order)


def cancel(company_id: int, db: Session, user_id: int, order_id: int, invoice_id: int, reason: str) -> dict:
    """POST .../{invoice_id}/cancel: 발주서 상태와 관계없이 취소 표시. 사유 필수, 이미 취소면 409. 행은 지우지 않는다."""
    order = get_owned(company_id, db, PurchaseOrder, order_id, lock=True)  # 404 (다른 회사 발주서)
    row = db.scalar(scoped(company_id, PurchaseTaxInvoice).where(
        PurchaseTaxInvoice.id == invoice_id, PurchaseTaxInvoice.purchase_order_id == order.id).with_for_update())
    if row is None:  # 다른 발주서·다른 회사의 계산서도 같은 404
        raise AppError(404, "NOT_FOUND", "대상을 찾을 수 없습니다.")
    reason = reason.strip()
    if not reason:
        raise AppError(422, "VALIDATION_ERROR", "취소 사유를 입력해 주세요.", [{"field": "reason", "reason": "required"}])
    if row.cancelled_at is not None:
        raise AppError(409, "ALREADY_CANCELLED", "이미 취소한 세금계산서입니다.")
    row.cancelled_at, row.cancelled_by, row.cancel_reason = datetime.now(UTC), user_id, reason
    db.flush()
    return view(company_id, db, order)
