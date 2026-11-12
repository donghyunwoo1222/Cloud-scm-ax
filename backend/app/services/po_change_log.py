"""발주서 변경 이력(#181). 이력은 이 파일의 log_change 한 곳에서만 쓴다(추가 전용, 수정·삭제 함수 없음).

커밋은 하지 않는다: 호출한 요청의 트랜잭션에 함께 들어가므로, 이력 저장이 실패하면 변경도 되돌려진다.
"""

from collections.abc import Iterable  # (항목, 전, 후) 묶음
from datetime import date  # 납기 값을 글자로

from sqlalchemy import insert  # 여러 행을 한 문장으로 넣는 INSERT
from sqlalchemy.orm import Session  # DB 세션

from app.models import PoChangeLog, PurchaseOrder, User
from app.pagination import PageParams, paginate  # 목록 쪽 나누기
from app.services.tenant import get_owned, scoped  # 회사 분리 도우미

Change = tuple[str, str | None, str | None]  # (바뀐 항목, 변경 전 값, 변경 후 값)


def text_of(value: object) -> str | None:
    """값을 이력에 저장할 글자로. 비어 있으면 None (예: 납기 2026-11-20 → '2026-11-20', 비움 → None)."""
    if value is None:
        return None
    return value.isoformat() if isinstance(value, date) else str(value)


def describe_line(values: dict) -> str:
    """줄 하나를 한 줄 문장으로. 예) '수량 120 · 단가 1,000원', 박스 줄은 '수량 120 · 단가 1,000원 · 박스 10개입 · 박스단가 10,000원'."""
    text = f"수량 {values['quantity']:,} · 단가 {values['unit_price']:,}원"
    if values.get("units_per_box") is not None:  # 박스 줄이면 당시 입수·박스 단가도
        text += f" · 박스 {values['units_per_box']:,}개입 · 박스단가 {values['box_unit_price']:,}원"
    return text


def log_change(db: Session, company_id: int, order_id: int, user_id: int, changes: Iterable[Change],
               reason: str | None = None) -> int:
    """바뀐 칸마다 한 행을 한 번의 INSERT 로 넣는다(줄마다 INSERT 하지 않는다). 전·후가 같은 칸은 행을 만들지 않는다. 넣은 행 수를 돌려준다."""
    rows = [
        {"company_id": company_id, "purchase_order_id": order_id, "field": field,
         "old_value": old, "new_value": new, "changed_by": user_id, "reason": reason}
        for field, old, new in changes if old != new
    ]
    if rows:
        db.execute(insert(PoChangeLog), rows)  # 시각은 DB 가 트랜잭션 시작 시각으로 채운다 → 한 요청의 행은 모두 같은 시각
    return len(rows)


def list_changes(company_id: int, db: Session, order_id: int, page: PageParams) -> tuple[list[dict], dict]:
    """GET /purchase-orders/{id}/change-log: 최신순. 다른 회사·없는 발주서는 404. 사용자는 이름만 내보낸다(이메일·번호 없음)."""
    get_owned(company_id, db, PurchaseOrder, order_id)  # 404
    rows, meta = paginate(db, scoped(company_id, PoChangeLog).where(
        PoChangeLog.purchase_order_id == order_id).order_by(PoChangeLog.id.desc()), page)
    names = dict(db.execute(scoped(company_id, User).with_only_columns(User.id, User.name).where(
        User.id.in_({r.changed_by for r in rows}))).all()) if rows else {}  # 사용자 번호 → 이름 (한 번에)
    return [
        {"id": r.id, "field": r.field, "old_value": r.old_value, "new_value": r.new_value,
         "changed_by_name": names.get(r.changed_by, ""), "reason": r.reason, "created_at": r.created_at}
        for r in rows
    ], meta
