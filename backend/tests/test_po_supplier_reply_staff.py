"""직원이 받은 공급업체 회신 기록 (#265 PR4): POST /purchase-orders/{id}/supplier-reply.

상태는 바꾸지 않고 회신 납기·확인 시각·변경 이력(행위자 = 직원, 사유 = 받은 경로)만 남긴다.
공개 링크의 5번 제한·회신 횟수에는 넣지 않는다. PR1 행렬(test_po_transitions.py)은 고치지 않고 여기서 상태 5 × 역할 2 를 본다.
"""

from datetime import timedelta  # 날짜 계산

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 이력 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import PoChangeLog, PurchaseOrder  # 표
from app.services import purchase_orders as po_service  # 동시 취소
from app.services import supplier_reply  # 대상 서비스
from app.services.po_states import allowed_actions  # 버튼 목록
from tests.concurrency import (  # 동시 요청 도구
    delayed,
    hold_row_lock,
    ordered_po,
    run_at_once,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_transitions import (  # P1 100개 발주서 만들기 (읽기만)
    EMAILS,
    STATES,
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
)

REASON = "11/19 전화, 김과장"


def record(client, po, due=None, reason=REASON):
    body = {"reason": reason}
    if due is not None:
        body["due_date"] = due.isoformat()
    return client.post(f"{URL}/{po['id']}/supplier-reply", json=body)


def error(r):
    e = r.json()["error"]
    return r.status_code, e["code"], e["details"]


def change_log(client, po) -> list[dict]:
    return client.get(f"{URL}/{po['id']}/change-log").json()["data"]


# ----- 상태 5 × 역할 2: 버튼(allowed_actions)과 서버가 양쪽으로 같다 -----
@pytest.mark.parametrize("role", ("staff", "admin"))
@pytest.mark.parametrize("state", STATES)
def test_allowed_matches_server(client, world, product, state, role):  # noqa: F811
    po = make_po(client, world, product, state)
    login_as(client, EMAILS[role])
    shown = "supplier_reply" in client.get(f"{URL}/{po['id']}").json()["data"]["allowed_actions"]
    r = record(client, po, seoul_today() + timedelta(days=3))
    assert shown == (state == "ORDERED")
    if shown:
        assert r.status_code == 200, r.json()
        assert r.json()["data"]["status"] == "ORDERED"  # 상태는 그대로
    else:
        assert error(r) == (409, "INVALID_STATUS", {"status": state})


def test_receipts_do_not_change_permission():
    """부분 입고된 ORDERED 도 기록 가능, 입고 완료(잔량 마감 포함)는 불가."""
    assert "supplier_reply" in allowed_actions("ORDERED", "STAFF", True)
    assert "supplier_reply" not in allowed_actions("RECEIVED", "ADMIN", True)


# ----- 기록 내용 -----
def test_staff_records_reply_without_token(client, world, product, session):  # noqa: F811
    """수동 '주문 완료'(토큰 없음) 발주에서 담당자가 기록: 회신 납기·확인 시각, 이력 행위자 = 직원, 사유 저장, 횟수 0."""
    po = make_po(client, world, product, "ORDERED")
    login_as(client)  # 담당자
    due = seoul_today() + timedelta(days=5)
    r = record(client, po, due)
    assert r.status_code == 200, r.json()
    out = r.json()["data"]
    assert out["supplier_due_date"] == due.isoformat() and out["supplier_confirmed_at"] and out["supplier_reply_count"] == 0
    order = session.get(PurchaseOrder, po["id"])
    assert order.supplier_token_hash is None  # 토큰 없이도 된다
    rows = {row["field"]: row for row in change_log(client, po) if row["field"].startswith("supplier_")}
    assert set(rows) == {"supplier_confirmed_at", "supplier_due_date"}
    for row in rows.values():
        assert row["changed_by_name"] == "a-STAFF" and row["reason"] == REASON  # '공급업체(메일 링크)' 가 아니다
    assert (rows["supplier_due_date"]["old_value"], rows["supplier_due_date"]["new_value"]) == (None, due.isoformat())


def test_confirm_only_and_same_date_is_idempotent(client, world, product, session):  # noqa: F811
    """날짜 없이 확인만 → 확인 시각 1행. 같은 날짜 두 번 → 두 번째는 이력 0행. 확인 시각은 처음 값 유지."""
    po = make_po(client, world, product, "ORDERED")
    assert record(client, po).status_code == 200  # 확인만
    first = session.get(PurchaseOrder, po["id"]).supplier_confirmed_at
    assert [r["field"] for r in change_log(client, po)][:1] == ["supplier_confirmed_at"]
    due = seoul_today() + timedelta(days=2)
    assert record(client, po, due).status_code == 200
    count = len(change_log(client, po))
    r = record(client, po, due)  # 같은 날짜 재입력
    assert r.status_code == 200 and len(change_log(client, po)) == count
    session.expire_all()
    assert session.get(PurchaseOrder, po["id"]).supplier_confirmed_at == first


def test_not_counted_in_public_limit(client, world, product, session):  # noqa: F811
    """공개 링크 회신 5번을 다 쓴 발주에도 직원은 기록할 수 있고, 횟수는 그대로 5."""
    po = make_po(client, world, product, "ORDERED")
    order = session.get(PurchaseOrder, po["id"])
    order.supplier_reply_count = supplier_reply.REPLY_LIMIT
    session.commit()
    r = record(client, po, seoul_today() + timedelta(days=9))
    assert r.status_code == 200, r.json()
    assert r.json()["data"]["supplier_reply_count"] == supplier_reply.REPLY_LIMIT


def test_partial_receipt_ok_then_closed_409(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    assert record(client, po, seoul_today()).status_code == 200  # 부분 입고: 남은 수량 도착일
    r = client.post(f"{URL}/{po['id']}/close-remaining", json={"reason": "잔량 미납"})
    assert r.status_code == 200, r.json()
    assert error(record(client, po, seoul_today())) == (409, "INVALID_STATUS", {"status": "RECEIVED"})


# ----- 검증 -----
@pytest.mark.parametrize("reason", ["", "   ", None])
def test_reason_required(client, world, product, reason):  # noqa: F811
    po = make_po(client, world, product, "ORDERED")
    body = {} if reason is None else {"reason": reason}
    r = client.post(f"{URL}/{po['id']}/supplier-reply", json=body)
    assert r.status_code == 422, r.json()
    assert not any(row["field"].startswith("supplier_") for row in change_log(client, po))  # 아무것도 안 남는다


def test_reason_max_500(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED")
    assert record(client, po, reason="가" * 501).status_code == 422
    assert record(client, po, reason="가" * 500).status_code == 200


def test_date_range_same_as_public(client, world, product):  # noqa: F811
    """어제·1년+1일은 422, 오늘·1년 뒤는 200 (공개 링크와 같은 check_reply_date)."""
    po = make_po(client, world, product, "ORDERED")
    today = seoul_today()
    for bad in (today - timedelta(days=1), supplier_reply.one_year_later(today) + timedelta(days=1)):
        assert error(record(client, po, bad)) == (422, "VALIDATION_ERROR", [{"field": "due_date", "reason": "out_of_range"}])
    for good in (today, supplier_reply.one_year_later(today)):
        assert record(client, po, good).status_code == 200


def test_rejects_extra_fields_and_other_company(client, world, product):  # noqa: F811
    """changed_by·company_id 를 보내면 422 (행위자는 로그인에서만). 다른 회사 사용자는 404."""
    po = make_po(client, world, product, "ORDERED")
    for extra in ({"changed_by": 1}, {"company_id": 999}, {"supplier_reply_count": 0}):
        r = client.post(f"{URL}/{po['id']}/supplier-reply", json={"reason": REASON, **extra})
        assert r.status_code == 422, extra
    login_as(client, "staff@b.test")
    assert record(client, po).status_code == 404


def test_public_view_keeps_allowed_keys_and_hides_reason(client, world, product, session):  # noqa: F811
    """직원 기록 뒤에도 공개 응답 키는 PUBLIC_KEYS 그대로이고 사유 글자는 어디에도 없다."""
    po = make_po(client, world, product, "ORDERED")
    record(client, po, seoul_today() + timedelta(days=4), reason="비밀메모-전화")
    data = supplier_reply.public_view(session, session.get(PurchaseOrder, po["id"]))
    assert tuple(data) == supplier_reply.PUBLIC_KEYS
    assert "비밀메모" not in repr(data)
    assert data["replies_left"] == supplier_reply.REPLY_LIMIT  # 공급업체의 남은 횟수가 줄지 않는다


# ----- 동시 요청 (실제 commit) -----
def test_concurrent_reply_and_cancel_serialized(engine, committed_company):
    """직원 기록과 취소를 동시에: 교착 없이 한 줄로. 취소가 먼저면 기록은 CANCELLED 를 보고 409, 기록이 먼저면 둘 다 성공."""
    data = committed_company
    order_id, _ = ordered_po(engine, data, [data["product_id"]])
    due = seoul_today() + timedelta(days=3)

    def reply():
        return run_in_new_session(engine, lambda s: supplier_reply.record_by_staff(
            data["company_id"], s, data["admin_id"], order_id, due, REASON).status)

    def cancel():
        return run_in_new_session(engine, lambda s: po_service.change_status(
            data["company_id"], s, data["admin_id"], order_id, "cancel", "취소").status)

    gate = hold_row_lock(engine, PurchaseOrder, order_id)
    replied, cancelled = run_at_once(gate, delayed(reply), delayed(cancel))[1:]
    assert cancelled == "CANCELLED"
    assert replied == "ORDERED" or getattr(replied, "code", None) == "INVALID_STATUS"
    logged = run_in_new_session(engine, lambda s: s.scalar(select(func.count()).select_from(PoChangeLog).where(
        PoChangeLog.purchase_order_id == order_id, PoChangeLog.field == "supplier_due_date")))
    assert logged == (1 if replied == "ORDERED" else 0)
