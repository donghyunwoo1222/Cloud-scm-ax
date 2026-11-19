"""발주서 allowed_actions · 입고 이력 can_correct · 오류 문장 한국어 테스트 (#260 PR3).

핵심: allowed_actions 가 PR1 특성화 행렬(test_po_transitions.ALLOWED, 실제 서버 동작)과 양쪽 방향으로 같은지 본다.
버튼에 보이는 동작은 서버가 받아 주고, 서버가 받아 주는 동작은 버튼에 보인다.
"""

import re  # 영어 상태값 찾기
from types import SimpleNamespace  # set_status 에 넘길 가짜 발주서

import pytest  # 테스트 도구

from app.errors import AppError  # 공통 오류
from app.services import purchase_orders as po_service  # set_status
from app.services.po_states import STATUS_NAMES, allowed_actions  # 검사 대상
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_transitions import (  # PR1 행렬과 준비 도구 (이 파일은 고치지 않고 읽기만)
    ALLOWED,
    STATES,
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
    receive,
)

ROLES = ("ADMIN", "STAFF")
ENGLISH = re.compile(r"DRAFT|APPROVED|ORDERED|RECEIVED|CANCELLED")  # 사용자 문장에 나오면 안 되는 상태 코드
MOVEMENTS = "/api/v1/inventory-movements"

# allowed_actions 이름 → 같은 동작의 PR1 행렬 이름들. email 은 미리보기 행렬과 같다
# (ORDERED 메일 POST 는 resend 없이 409 ALREADY_ORDERED, 다시 보내기 확인 뒤 허용 → test_po_transitions OTHER 참고)
MATRIX = {
    "edit": ("edit",), "approve": ("approve",), "order": ("order",), "cancel": ("cancel",),
    "email": ("email_preview",), "receive": ("receive",), "document": ("document", "document_xlsx"),
}
NOT_IN_MATRIX = {"supplier_reply"}  # PR1 행렬 이후 추가된 동작: test_po_supplier_reply_staff.py 가 상태 5 × 역할 2 를 따로 검사한다


def server_allows(action: str, state: str, role: str) -> bool:
    """PR1 행렬 기준으로 서버가 이 동작을 받아 주는지 (입고 기록 0건). 승인은 담당자면 모든 상태 403."""
    if action == "approve" and role == "STAFF":
        return False
    allowed = [state in ALLOWED[name] for name in MATRIX[action]]
    assert len(set(allowed)) == 1, (action, state)  # 문서·엑셀처럼 묶인 행렬끼리도 같아야 한다
    return allowed[0]


# ----- 순수 함수: 상태 5 × 역할 2 × 입고 유무 -----
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("state", STATES)
def test_allowed_actions_match_matrix_both_ways(state, role):
    """입고 0건: allowed_actions 에 있는 동작 == 행렬이 허용하는 동작 (양쪽 방향)."""
    shown = set(allowed_actions(state, role, has_receipts=False)) - NOT_IN_MATRIX
    assert shown <= set(MATRIX), shown  # 모르는 이름이 없다
    expected = {action for action in MATRIX if server_allows(action, state, role)}
    assert shown == expected, (state, role)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("state", STATES)
def test_receipts_only_remove_cancel(state, role):
    """입고 기록이 있으면 취소만 빠지고(CANNOT_CANCEL_RECEIVED), ORDERED 면 그 자리에 잔량 마감이 생긴다(#252, NO_RECEIPTS 의 반대)."""
    without = allowed_actions(state, role, has_receipts=False)
    added = ["close_remaining"] if state == "ORDERED" else []
    assert "close_remaining" not in without  # 입고 0건이면 잔량 마감 없음
    assert allowed_actions(state, role, has_receipts=True) == [
        b for a in without for b in (added if a == "cancel" else [a])]  # 취소 자리를 잔량 마감이 대신한다


def test_allowed_actions_examples():
    """눈으로 읽는 예: 순서는 edit, approve, order, cancel, close_remaining, email, receive, supplier_reply, document."""
    assert allowed_actions("DRAFT", "ADMIN", False) == ["edit", "approve", "cancel"]
    assert allowed_actions("DRAFT", "STAFF", False) == ["edit", "cancel"]
    assert allowed_actions("APPROVED", "STAFF", False) == ["order", "cancel", "email", "document"]
    assert allowed_actions("ORDERED", "STAFF", True) == ["close_remaining", "email", "receive", "supplier_reply", "document"]
    assert allowed_actions("ORDERED", "ADMIN", True) == ["close_remaining", "email", "receive", "supplier_reply", "document"]
    assert allowed_actions("RECEIVED", "ADMIN", True) == ["document"]
    assert allowed_actions("CANCELLED", "ADMIN", False) == []


# ----- API: 목록·상세에 들어 있고 역할을 반영한다 -----
def test_api_list_and_detail_carry_allowed_actions(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "DRAFT")  # 담당자로 로그인된 채 끝난다
    detail = client.get(f"{URL}/{po['id']}").json()["data"]
    listed = next(o for o in client.get(URL).json()["data"] if o["id"] == po["id"])
    assert detail["allowed_actions"] == listed["allowed_actions"] == ["edit", "cancel"]  # 담당자: 승인 없음

    login_as(client, "admin@a.test")
    detail = client.get(f"{URL}/{po['id']}").json()["data"]
    listed = next(o for o in client.get(URL).json()["data"] if o["id"] == po["id"])
    assert detail["allowed_actions"] == listed["allowed_actions"] == ["edit", "approve", "cancel"]  # 관리자: 승인 있음


def test_api_partial_receipt_hides_cancel(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "ORDERED", received=40)
    assert po["has_receipts"] is True
    assert po["allowed_actions"] == ["close_remaining", "email", "receive", "supplier_reply", "document"]  # 취소 대신 잔량 마감 (#252)


# ----- can_correct 5가지 -----
def movement(client, movement_id: int) -> dict:
    return next(m for m in client.get(MOVEMENTS).json()["data"] if m["id"] == movement_id)


def latest_receipt_id(client) -> int:
    return client.get(MOVEMENTS, params={"movement_type": "RECEIPT", "sort": "registered"}).json()["data"][0]["id"]


def correct(client, movement_id: int, quantity: int):
    r = client.post(f"{MOVEMENTS}/{movement_id}/corrections", json={"quantity": quantity, "reason": "오입력"})
    assert r.status_code == 201, r.json()
    return r.json()["data"]


def test_can_correct_ordered_receipt_and_correction_rows(client, world, product):  # noqa: F811
    """① ORDERED 발주의 입고 행 → 정정 가능, ④ 정정 이력 행 → 불가."""
    make_po(client, world, product, "ORDERED", received=40)
    receipt_id = latest_receipt_id(client)
    assert movement(client, receipt_id)["can_correct"] is True
    fix = correct(client, receipt_id, 10)
    assert movement(client, fix["id"])["can_correct"] is False
    assert movement(client, receipt_id)["can_correct"] is True  # 30 남음


def test_can_correct_received_receipt_is_false(client, world, product):  # noqa: F811
    """② RECEIVED 가 된 발주의 입고 행 → 남은 수량이 있어도 불가 (create_correction 이 409)."""
    make_po(client, world, product, "RECEIVED")
    row = movement(client, latest_receipt_id(client))
    assert row["correctable_quantity"] == 100 and row["can_correct"] is False


def test_can_correct_direct_receipt(client, world, product):  # noqa: F811
    """③ 발주 연결 없는 직접 입고 → 정정 가능."""
    login_as(client)
    r = client.post(MOVEMENTS, json={"product_id": product.id, "movement_type": "RECEIPT", "quantity": 5,
                                     "confirm_warnings": True})
    assert r.status_code == 201, r.json()
    row = movement(client, r.json()["data"]["id"])
    assert row["purchase_order_id"] is None and row["can_correct"] is True


def test_can_correct_fully_corrected_is_false(client, world, product):  # noqa: F811
    """⑤ 전량 정정된 행 → 불가 (남은 수량 0)."""
    make_po(client, world, product, "ORDERED", received=40)
    receipt_id = latest_receipt_id(client)
    correct(client, receipt_id, 40)
    row = movement(client, receipt_id)
    assert row["correctable_quantity"] == 0 and row["can_correct"] is False


# ----- 오류 문장에 영어 상태값이 없다 (details 는 그대로 {"status": 코드}) -----
def assert_korean(r, state: str):
    e = r.json()["error"]
    assert (r.status_code, e["code"], e["details"]) == (409, "INVALID_STATUS", {"status": state})
    assert not ENGLISH.search(e["message"]), e["message"]
    assert STATUS_NAMES[state] in e["message"], e["message"]  # 현재 상태를 한국어로 알려 준다


def test_invalid_status_messages_are_korean(client, world, product):  # noqa: F811
    po = make_po(client, world, product, "RECEIVED")  # 관리자로 로그인된 채 끝난다
    assert_korean(client.patch(f"{URL}/{po['id']}", json={"memo": "x"}), "RECEIVED")  # 수정 (update_order)
    assert_korean(client.post(f"{URL}/{po['id']}/approve"), "RECEIVED")  # 전이 (change_status)
    assert_korean(receive(client, po, 1), "RECEIVED")  # 입고 (receive_order)
    r = client.post(f"{MOVEMENTS}/{latest_receipt_id(client)}/corrections", json={"quantity": 1, "reason": "오입력"})
    assert_korean(r, "RECEIVED")  # 입고 정정 (create_correction)


@pytest.mark.parametrize("state", STATES)
def test_set_status_message_is_korean(state):
    """set_status 의 안전망 문장 (API 로는 change_status 가 먼저 막아 닿지 않는다). DB 를 쓰기 전에 거절한다."""
    order = SimpleNamespace(status=state)
    action = "complete_receipt" if state != "ORDERED" else "approve"  # 어느 경우든 표에 없는 이동
    with pytest.raises(AppError) as caught:
        po_service.set_status(None, 1, order, 1, action)
    assert caught.value.code == "INVALID_STATUS" and not ENGLISH.search(caught.value.message)
