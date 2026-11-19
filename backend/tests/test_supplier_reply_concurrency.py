"""공급업체 확인 동시성 (#265 PR2): 진짜 commit 하는 연결 여러 개로 발주서 행 잠금을 확인한다(tests/concurrency.py 방식)."""

from datetime import timedelta  # 회신 날짜

import pytest  # 테스트 도구
from sqlalchemy import func, select  # DB 시각, 조회

from app.auth.security import hash_reset_token  # 토큰 해시
from app.clock import seoul_today  # 서울 기준 오늘
from app.config import settings  # 스위치
from app.errors import AppError  # 거절 오류
from app.models import PoChangeLog, PurchaseOrder  # 확인할 표
from app.services import purchase_orders as po_service  # 취소
from app.services import supplier_reply  # 대상
from tests.concurrency import delayed, hold_row_lock, ordered_po, run_at_once, run_in_new_session

TOKEN = "concurrency-test-token"  # 테스트 전용 값 (발급 토큰이 아님)


@pytest.fixture
def linked_po(engine, committed_company, monkeypatch):
    """토큰이 걸린 ORDERED 발주서 (진짜 commit) → (회사 데이터, 발주서 id)."""
    monkeypatch.setattr(settings, "supplier_link_enabled", True)
    order_id, _ = ordered_po(engine, committed_company, [committed_company["product_id"]])

    def link(s):
        po = s.get(PurchaseOrder, order_id)
        po.supplier_token_hash, po.supplier_token_expires_at = hash_reset_token(TOKEN), func.now() + timedelta(days=1)
        s.commit()

    run_in_new_session(engine, link)
    return committed_company, order_id


def read(engine, order_id):
    def fn(s):
        po = s.get(PurchaseOrder, order_id)
        rows = [(r.id, r.field, r.new_value) for r in s.scalars(
            select(PoChangeLog).where(PoChangeLog.purchase_order_id == order_id).order_by(PoChangeLog.id))]
        return po.status, po.supplier_reply_count, po.supplier_due_date, rows
    return run_in_new_session(engine, fn)


def test_cancel_and_confirm_at_once_stay_consistent(engine, linked_po):
    data, order_id = linked_po
    due = seoul_today() + timedelta(days=3)
    cancel = lambda: run_in_new_session(engine, lambda s: po_service.change_status(
        data["company_id"], s, data["admin_id"], order_id, "cancel", "공급 중단"))
    reply = lambda: run_in_new_session(engine, lambda s: supplier_reply.confirm(s, TOKEN, due))
    _, cancelled, replied = run_at_once(hold_row_lock(engine, PurchaseOrder, order_id), delayed(cancel), delayed(reply))
    assert not isinstance(cancelled, Exception)  # 취소는 언제나 성공한다 (확인은 상태를 바꾸지 않으므로 취소를 막지 않는다)
    status, count, saved_due, rows = read(engine, order_id)
    assert status == "CANCELLED"
    supplier_rows = [r for r in rows if r[1].startswith("supplier_")]
    status_row = next(r for r in rows if r[1] == "status" and r[2] == "CANCELLED")
    if isinstance(replied, AppError):  # 취소가 먼저: 확인은 잠금 뒤 CANCELLED 를 보고 거절, 기록 없음
        assert replied.code == "SUPPLIER_REPLY_CLOSED" and supplier_rows == [] and count == 0 and saved_due is None
    else:  # 확인이 먼저: 확인 기록이 취소 이력보다 앞에 있고 값이 남는다
        assert len(supplier_rows) == 2 and all(r[0] < status_row[0] for r in supplier_rows)
        assert count == 1 and saved_due == due


def test_same_confirm_twice_at_once_logs_once(engine, linked_po):
    _, order_id = linked_po
    due = seoul_today() + timedelta(days=4)
    reply = lambda: run_in_new_session(engine, lambda s: supplier_reply.confirm(s, TOKEN, due))
    results = run_at_once(hold_row_lock(engine, PurchaseOrder, order_id), delayed(reply), delayed(reply))
    assert not any(isinstance(r, Exception) for r in results[1:])  # 둘 다 200 (두 번째는 같은 값이라 변화 없음)
    _, count, saved_due, rows = read(engine, order_id)
    assert count == 1 and saved_due == due
    assert sorted(r[1] for r in rows if r[1].startswith("supplier_")) == ["supplier_confirmed_at", "supplier_due_date"]
