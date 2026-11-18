"""잔량 마감 close_remaining 테스트 (#252): 부분 입고된 ORDERED 발주를 사유를 적어 RECEIVED 로 닫는다.

마감 수량은 저장하지 않고 발주 − 누적 입고로 계산한다(응답 ItemOut.closed_quantity, 변경 이력 items[SKU].closed_quantity).
앞쪽은 API 테스트(테스트 세션, 끝나면 되돌림), 뒤쪽은 실제 commit 하는 동시 요청 테스트(tests/concurrency.py 도구).
"""

from datetime import datetime, timedelta  # 응답 시각 읽기, 지난 입고일

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 이력 세기

from app.clock import SEOUL, seoul_today  # 서울 시간대·오늘
from app.models import InventoryMovement, PoChangeLog, PurchaseOrder  # 표
from app.schemas.movements import CorrectionCreate  # 정정 요청 모양
from app.schemas.purchase_orders import ReceiptCreate  # 입고 요청 모양
from app.services import purchase_orders as po_service  # 잔량 마감·입고 서비스
from app.services import stock as stock_service  # 입고 정정
from app.services.dashboard import open_orders  # 대시보드 진행 중 발주
from app.services.recommendations import in_transit  # 추천의 발주 진행 중 수량
from tests.concurrency import (  # 동시 요청 도구
    delayed,
    hold_row_lock,
    ordered_po,
    run_at_once,
    run_in_new_session,
)
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_allowed_actions import (  # 입고 이력 도구 (읽기만)
    correct,
    latest_receipt_id,
    movement,
)
from tests.test_po_transitions import (  # P1 100개 발주서 만들기 (읽기만)
    EMAILS,
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
    receive,
)

REASON = "공급업체 재고 소진으로 잔량 미납"


def close(client, po, reason=REASON):
    body = {} if reason is None else {"reason": reason}
    return client.post(f"{URL}/{po['id']}/close-remaining", json=body)


def error(r):
    e = r.json()["error"]
    return r.status_code, e["code"], e["details"]


# ----- 정상 마감 -----
def test_close_partial_order(client, world, product, session):  # noqa: F811
    """100개 중 95개 입고(이틀 전·어제 두 번) → 마감: RECEIVED, received_at 은 마지막 입고일, closed_quantity 5, 이력에 사유와 줄별 마감 수량."""
    po = make_po(client, world, product, "ORDERED")  # 관리자로 로그인된 채 끝난다
    item_id = po["items"][0]["id"]
    for days, qty in ((2, 60), (1, 35)):
        r = client.post(f"{URL}/{po['id']}/receipts", json={
            "movement_date": (seoul_today() - timedelta(days=days)).isoformat(),
            "items": [{"purchase_order_item_id": item_id, "quantity": qty}]})
        assert r.status_code == 201, r.json()

    company_id = world["a_company"].id
    assert in_transit(company_id, session)[product.id] == 5  # 마감 전: 못 온 5개가 진행 중
    assert open_orders(company_id, session, seoul_today())["ordered"] == 1

    login_as(client)  # 담당자도 할 수 있다
    r = close(client, po)
    assert r.status_code == 200, r.json()
    out = r.json()["data"]
    assert out["status"] == "RECEIVED"
    assert datetime.fromisoformat(out["received_at"]).astimezone(SEOUL).date() == seoul_today() - timedelta(days=1)  # 마감한 오늘이 아니라 마지막 입고일
    assert out["items"][0]["received_quantity"] == 95 and out["items"][0]["closed_quantity"] == 5
    assert out["allowed_actions"] == ["document"]  # 되돌리기 없음

    rows = client.get(f"{URL}/{po['id']}/change-log").json()["data"]
    latest = {row["field"]: row for row in rows[:2]}  # 이번 요청이 남긴 두 행
    assert (latest["status"]["old_value"], latest["status"]["new_value"], latest["status"]["reason"]) == ("ORDERED", "RECEIVED", REASON)
    line = latest["items[P1].closed_quantity"]
    assert (line["old_value"], line["new_value"], line["reason"]) == (None, "5", REASON)

    assert product.id not in in_transit(company_id, session)  # 추천: 더 오지 않는다
    dash = open_orders(company_id, session, seoul_today())
    assert dash["ordered"] == 0 and dash["incoming_quantity"] == 0  # 대시보드: 진행 중에서 빠진다


def test_closed_quantity_null_before_received_and_zero_after_full_receipt(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    assert po["items"][0]["closed_quantity"] is None  # RECEIVED 가 아니면 null
    full = make_po(client, world, product, "RECEIVED")  # 다 받은 발주는 마감 수량 0
    assert full["items"][0]["closed_quantity"] == 0


def test_fully_corrected_order_can_close(client, world, product):  # noqa: F811
    """40 입고 → 40 전량 정정(누적 입고 0)이어도 입고 기록이 있으면 마감할 수 있다 (취소는 막힌다)."""
    po = make_po(client, world, product, "ORDERED", received=40)
    correct(client, latest_receipt_id(client), 40)
    po = client.get(f"{URL}/{po['id']}").json()["data"]
    assert po["items"][0]["received_quantity"] == 0 and po["has_receipts"] is True
    assert "close_remaining" in po["allowed_actions"] and "cancel" not in po["allowed_actions"]
    r = close(client, po)
    assert r.status_code == 200, r.json()
    assert r.json()["data"]["items"][0]["closed_quantity"] == 100


# ----- 거절 -----
@pytest.mark.parametrize("reason", [None, "", "   "], ids=["missing", "empty", "blank"])
def test_reason_required(client, world, product, reason):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    r = close(client, po, reason)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get(f"{URL}/{po['id']}").json()["data"]["status"] == "ORDERED"  # 아무것도 바뀌지 않았다


def test_no_receipts_is_409(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED")
    r = close(client, po)
    assert error(r)[:2] == (409, "NO_RECEIPTS") and "취소" in r.json()["error"]["message"]  # 다음에 할 일(취소)을 알려 준다


@pytest.mark.parametrize("state", ["DRAFT", "APPROVED", "RECEIVED", "CANCELLED"])
def test_other_states_invalid_status(client, world, product, state):  # noqa: F811
    po = make_po(client, world, product, state)
    assert error(close(client, po)) == (409, "INVALID_STATUS", {"status": state})  # 기존 INVALID_STATUS 모양 그대로


def test_other_company_is_404(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    login_as(client, "admin@b.test")
    assert close(client, po).status_code == 404


# ----- 마감 뒤 -----
def test_after_close_receipt_and_correction_blocked(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    assert close(client, po).status_code == 200
    assert error(receive(client, po, 1)) == (409, "INVALID_STATUS", {"status": "RECEIVED"})  # 입고 막힘
    receipt_id = latest_receipt_id(client)
    assert movement(client, receipt_id)["can_correct"] is False
    r = client.post(f"/api/v1/inventory-movements/{receipt_id}/corrections", json={"quantity": 1, "reason": "오입력"})
    assert error(r) == (409, "INVALID_STATUS", {"status": "RECEIVED"})  # 정정 막힘 → 마감 수량이 다시 바뀌지 않는다
    assert error(close(client, po)) == (409, "INVALID_STATUS", {"status": "RECEIVED"})  # 두 번 마감 불가


# ----- allowed_actions 에 있으면 서버도 허용한다 (양쪽 방향) -----
@pytest.mark.parametrize("role", ["staff", "admin"])
@pytest.mark.parametrize("state, received", [
    ("DRAFT", 0), ("APPROVED", 0), ("ORDERED", 0), ("ORDERED", 40), ("RECEIVED", 0), ("CANCELLED", 0),
])
def test_allowed_actions_match_server(client, world, product, state, received, role):  # noqa: F811
    po = make_po(client, world, product, state, received=received)
    login_as(client, EMAILS[role])
    po = client.get(f"{URL}/{po['id']}").json()["data"]
    shown = "close_remaining" in po["allowed_actions"]
    assert shown == (state == "ORDERED" and received > 0)
    if state == "ORDERED":
        assert ("cancel" in po["allowed_actions"]) != shown  # ORDERED 에서는 취소·잔량 마감 중 정확히 하나
    assert (close(client, po).status_code == 200) == shown


# ----- 동시 요청 (실제 commit) -----
def close_call(engine, data, order_id):
    return lambda: run_in_new_session(engine, lambda s: po_service.close_remaining(
        data["company_id"], s, data["admin_id"], order_id, REASON).status)


def receive_call(engine, data, order_id, item_id, quantity):
    body = ReceiptCreate(items=[{"purchase_order_item_id": item_id, "quantity": quantity}])
    return lambda: run_in_new_session(engine, lambda s: po_service.receive_order(
        data["company_id"], s, data["admin_id"], order_id, body).status)


def outcome(r):
    return r if isinstance(r, str) else getattr(r, "code", repr(r))  # 성공이면 상태, 실패면 오류 코드


def test_concurrent_close_and_receipt_one_wins(engine, committed_company):
    """95 입고된 발주에 마감과 남은 5 입고를 동시에: 하나만 성공, 다른 하나는 RECEIVED 를 보고 409."""
    data = committed_company
    order_id, (item_id,) = ordered_po(engine, data, [data["product_id"]])
    receive_call(engine, data, order_id, item_id, 95)()
    gate = hold_row_lock(engine, PurchaseOrder, order_id)
    closed, received = run_at_once(gate, delayed(close_call(engine, data, order_id)),
                                   delayed(receive_call(engine, data, order_id, item_id, 5)))[1:]
    assert (outcome(closed), outcome(received)) in (("RECEIVED", "INVALID_STATUS"), ("INVALID_STATUS", "RECEIVED"))
    total = run_in_new_session(engine, lambda s: po_service.received_quantities(data["company_id"], s, [item_id])[item_id])
    assert total == (95 if outcome(closed) == "RECEIVED" else 100)


def test_concurrent_closes_apply_once(engine, committed_company):
    data = committed_company
    order_id, (item_id,) = ordered_po(engine, data, [data["product_id"]])
    receive_call(engine, data, order_id, item_id, 30)()
    gate = hold_row_lock(engine, PurchaseOrder, order_id)
    results = run_at_once(gate, *[delayed(close_call(engine, data, order_id)) for _ in range(8)])[1:]
    assert results.count("RECEIVED") == 1
    assert all(outcome(r) == "INVALID_STATUS" for r in results if r != "RECEIVED")
    lines = run_in_new_session(engine, lambda s: s.scalar(select(func.count()).select_from(PoChangeLog).where(
        PoChangeLog.purchase_order_id == order_id, PoChangeLog.field.like("%closed_quantity"))))
    assert lines == 1  # 마감 이력도 한 번만


def test_concurrent_close_and_correction_serialized(engine, committed_company):
    """마감과 입고 정정을 동시에: 교착 없이 한 줄로 처리되고, 이력의 마감 수량 = 발주 − 최종 누적 입고."""
    data = committed_company
    order_id, (item_id,) = ordered_po(engine, data, [data["product_id"]])
    receive_call(engine, data, order_id, item_id, 90)()
    receipt_id = run_in_new_session(engine, lambda s: s.scalar(select(InventoryMovement.id).where(
        InventoryMovement.purchase_order_item_id == item_id)))

    def fix():
        return run_in_new_session(engine, lambda s: (stock_service.create_correction(
            data["company_id"], s, data["admin_id"], receipt_id, CorrectionCreate(quantity=10, reason="오입력")), "CORRECTED")[1])

    gate = hold_row_lock(engine, PurchaseOrder, order_id)
    closed, fixed = run_at_once(gate, delayed(close_call(engine, data, order_id)), delayed(fix))[1:]
    assert outcome(closed) == "RECEIVED"  # 마감은 정정 앞이든 뒤든 성공한다
    assert outcome(fixed) in ("CORRECTED", "INVALID_STATUS")  # 정정은 마감보다 먼저면 성공, 뒤면 RECEIVED 를 보고 409
    total = run_in_new_session(engine, lambda s: po_service.received_quantities(data["company_id"], s, [item_id])[item_id])
    logged = run_in_new_session(engine, lambda s: s.scalar(select(PoChangeLog.new_value).where(
        PoChangeLog.purchase_order_id == order_id, PoChangeLog.field.like("%closed_quantity"))))
    assert int(logged) == 100 - total  # 이력과 계산 값이 어긋나지 않는다 (정정 먼저면 20, 마감 먼저면 10)

