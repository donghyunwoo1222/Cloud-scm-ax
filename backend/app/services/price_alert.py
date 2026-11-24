"""발주 단가 변동 경고 (#283). 저장·승인을 막지 않고, 작성 화면이 단가 칸 아래에 문장만 보여 준다.

비교 대상: 같은 공급업체·같은 품목의 승인 이상(APPROVED·ORDERED·RECEIVED) 원화 발주 중 가장 최근 승인 시각의 줄.
판정은 float 없이 정확한 분수(Fraction)로 한다. 예) 직전 1,000원, 임계 10%: 1,100원은 경고(정확히 10%), 1,099원은 경고 없음.
"""

from fractions import Fraction  # 정확한 분수(박스 단가 ÷ 입수도 오차 없이)
from math import floor  # 내림

from sqlalchemy import select  # SELECT 문
from sqlalchemy.dialects.postgresql import distinct_on  # PostgreSQL DISTINCT ON
from sqlalchemy.orm import Session  # DB 세션 타입

from app.clock import SEOUL  # 승인 시각을 서울 날짜로
from app.config import settings  # PRICE_ALERT_PERCENT
from app.models import PurchaseOrder, PurchaseOrderItem, Supplier  # 표들
from app.schemas.purchase_orders import PriceCheck  # 요청 모양
from app.services.tenant import check_ref  # 다른 회사 공급업체는 404

COMPARE_STATES = ("APPROVED", "ORDERED", "RECEIVED")  # 승인 이상. DRAFT(수정 중인 자기 자신 포함)와 CANCELLED 는 빠진다


def price_alert(new_price: int | None, previous: Fraction | None, percent: int) -> tuple[str, int] | None:
    """순수 함수: (방향, 표시 퍼센트) 또는 경고 없음(None). 방향은 UP·DOWN, 새 단가 0원이면 ZERO.

    new_price 가 None(입력 비어 있음)이거나 직전이 없거나 0원이면 퍼센트를 낼 수 없어 None 이다.
    판정은 |새−옛|×100 ≥ percent×옛 (정수 곱셈), 표시 퍼센트는 내림(경고가 뜨면 표시 값은 항상 임계 이상).
    """
    if new_price is None or previous is None or previous <= 0:
        return None
    gap = abs(new_price - previous)  # 옛과 새의 차이(분수)
    if gap * 100 < percent * previous:  # 임계 미만이면 알리지 않는다
        return None
    shown = floor(gap * 100 / previous)  # 예) 1000 → 1250 은 25
    if new_price == 0:
        return "ZERO", shown
    return ("UP" if new_price > previous else "DOWN"), shown


def message(direction: str, percent: int, previous: int, po_number: str, month_day: str) -> str:
    """경고 문장. 예) 지난번 1,000원보다 25% 높습니다 (PO-20261002-001, 10/02)"""
    if direction == "ZERO":
        return f"단가가 0원입니다 (지난번 {previous:,}원, {po_number}, {month_day})"
    word = "높습니다" if direction == "UP" else "낮습니다"
    return f"지난번 {previous:,}원보다 {percent}% {word} ({po_number}, {month_day})"


def previous_lines(company_id: int, db: Session, supplier_id: int, product_ids: set[int]) -> dict:
    """품목마다 직전 발주의 줄 한 건(쿼리 한 번). 승인 시각이 같으면 발주서 내부 id(purchase_orders.id)가 큰 쪽. 승인 시각이 없는 발주는 비교하지 않는다."""
    stmt = (
        select(PurchaseOrderItem, PurchaseOrder)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(
            PurchaseOrderItem.company_id == company_id, PurchaseOrder.company_id == company_id,  # 회사 분리
            PurchaseOrder.supplier_id == supplier_id,
            PurchaseOrder.status.in_(COMPARE_STATES),
            PurchaseOrder.currency == "KRW",  # 외화 발주는 비교하지 않는다
            PurchaseOrder.approved_at.is_not(None),  # 승인 시각이 비어 있는 데이터는 건너뛴다 (문장에 날짜가 필요하다)
            PurchaseOrderItem.product_id.in_(product_ids),
        )
        .ext(distinct_on(PurchaseOrderItem.product_id))  # 품목마다 첫 줄만
        .order_by(PurchaseOrderItem.product_id, PurchaseOrder.approved_at.desc(), PurchaseOrder.id.desc())
    )
    return {item.product_id: (item, order) for item, order in db.execute(stmt)}


def per_unit(item: PurchaseOrderItem) -> Fraction | None:
    """줄의 개당 가격. 박스 줄은 박스 단가 ÷ 입수(박스 줄의 unit_price 는 마스터 복사값이라 쓰지 않는다)."""
    if item.units_per_box is not None:
        return None if item.box_unit_price is None else Fraction(item.box_unit_price, item.units_per_box)
    return None if item.unit_price is None else Fraction(item.unit_price)


def check(company_id: int, db: Session, data: PriceCheck) -> list[dict]:
    """요청 줄마다 {product_id, unit_price, alert}. alert 는 경고가 없으면 None."""
    check_ref(company_id, db, Supplier, data.supplier_id, "supplier_id")  # 다른 회사·없는 공급업체는 404
    wanted = {i.product_id for i in data.items if i.unit_price is not None}  # 가격을 입력한 품목만 찾는다
    found = previous_lines(company_id, db, data.supplier_id, wanted) if wanted else {}
    out = []
    for i in data.items:
        alert = None
        hit = found.get(i.product_id)
        previous = per_unit(hit[0]) if hit else None
        result = price_alert(i.unit_price, previous, settings.price_alert_percent)
        if result is not None:
            direction, percent = result
            _, order = hit
            shown = floor(previous + Fraction(1, 2))  # 표시용 원 단위(반올림). 판정에는 쓰지 않는다
            month_day = order.approved_at.astimezone(SEOUL).strftime("%m/%d")
            alert = {
                "direction": direction, "percent": percent, "previous_unit_price": shown,
                "po_id": order.id, "po_number": order.po_number, "approved_on": order.approved_at.astimezone(SEOUL).date(),
                "message": message(direction, percent, shown, order.po_number, month_day),
            }
        out.append({"product_id": i.product_id, "unit_price": i.unit_price, "alert": alert})
    return out
