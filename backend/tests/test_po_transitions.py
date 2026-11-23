"""발주서 상태 전이 특성화 테스트 (#260 PR1): 지금 코드가 실제로 어떻게 동작하는지 그대로 고정한다.

앱 코드를 바꾸지 않고 통과해야 한다. 나중에 동작을 의도적으로 바꾸면 여기 기대값을 함께 고친다.
"# 현재 동작 고정(이슈 #N)" 주석이 붙은 칸은 그 이슈에서 바뀔 예정인 칸이다.
상태는 DB 에 직접 넣지 않고 실제 API 흐름(작성 → 승인 → 주문 → 입고 → 취소)으로 만든다.
"CANCELLED + 입고 이력" 칸은 만들 수 없다: 입고 기록이 있으면 취소가 막히므로 API 로 도달 불가 (state-machines.md 참고).
"""

import smtplib  # 실제 SMTP 접속을 막고, 발송 실패를 흉내 낸다

import pytest  # 테스트 도구

from app.config import settings  # SMTP 설정 (테스트 동안만 바꾸고 monkeypatch 가 되돌린다)
from app.models import Product  # 품목 표
from app.services import po_mail  # 바꿔 끼울 발송 함수
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/purchase-orders"  # 발주 경로
STATES = ("DRAFT", "APPROVED", "ORDERED", "RECEIVED", "CANCELLED")  # 발주서 상태 5개
EMAILS = {"staff": "staff@a.test", "admin": "admin@a.test"}  # 역할 → 회사 A 사용자


# ----- 준비 도구 -----
@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    """가짜 메일 서버: 실제로 보내지 않고 목록에 담는다. monkeypatch 가 테스트 끝에 설정·함수를 되돌린다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")  # 설정이 있는 것처럼 (없으면 503 MAIL_NOT_CONFIGURED)
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(po_mail, "deliver", sent.append)  # 발송 = 목록에 담기

    def no_network(*args, **kwargs):  # 혹시 deliver 를 거치지 않고 SMTP 를 열면 바로 실패
        raise AssertionError("테스트에서 실제 SMTP 접속 시도")
    monkeypatch.setattr(smtplib, "SMTP", no_network)
    monkeypatch.setattr(smtplib, "SMTP_SSL", no_network)
    return sent


@pytest.fixture
def product(world, session):
    """회사 A 의 품목 P1 (기본 공급업체 A업체). 공급업체에 이메일을 넣어 메일 발송이 가능하게 한다."""
    world["a_supplier"].email = "sales@a-supplier.test"
    p = Product(company_id=world["a_company"].id, sku="P1", name="품목1", unit="개", unit_cost=1000,
                default_supplier_id=world["a_supplier"].id)
    session.add(p)
    session.commit()
    return p


def make_po(client, world, product, state: str, received: int = 0) -> dict:
    """실제 API 로 P1 100개짜리 발주서를 state 까지 만든다 → 응답 data. received 는 ORDERED 에서 부분 입고할 수량."""
    login_as(client)  # 작성은 담당자
    r = client.post(URL, json={"supplier_id": world["a_supplier"].id,
                               "items": [{"product_id": product.id, "quantity": 100, "unit_price": 800}]})
    assert r.status_code == 201, r.json()
    po = r.json()["data"]
    if state == "CANCELLED":  # DRAFT 에서 취소 (사유 선택)
        r = client.post(f"{URL}/{po['id']}/cancel")
    if state in ("APPROVED", "ORDERED", "RECEIVED"):
        login_as(client, "admin@a.test")  # 승인은 관리자
        r = client.post(f"{URL}/{po['id']}/approve")
    if state in ("ORDERED", "RECEIVED"):
        r = client.post(f"{URL}/{po['id']}/order")
    qty = 100 if state == "RECEIVED" else received
    if qty:
        r = receive(client, po, qty)
    if state != "DRAFT":
        assert r.status_code in (200, 201), r.json()
    po = client.get(f"{URL}/{po['id']}").json()["data"]
    assert po["status"] == state  # 준비가 맞게 됐는지
    return po


def receive(client, po, qty):
    return client.post(f"{URL}/{po['id']}/receipts",
                       json={"items": [{"purchase_order_item_id": po["items"][0]["id"], "quantity": qty}]})


def status_of(client, po) -> str:
    return client.get(f"{URL}/{po['id']}").json()["data"]["status"]


def error(r):
    """(HTTP, 오류 코드, details). 문장은 비교하지 않는다."""
    e = r.json()["error"]
    return r.status_code, e["code"], e["details"]


def receipt_movement_id(client) -> int:
    """가장 최근 입고(RECEIPT) 이력 번호."""
    return client.get("/api/v1/inventory-movements", params={"movement_type": "RECEIPT"}).json()["data"][0]["id"]


def status_changes(client, po) -> list[tuple[str, str]]:
    """변경 이력의 status 행만 (이전, 이후), 오래된 순."""
    rows = client.get(f"{URL}/{po['id']}/change-log").json()["data"]
    return [(r["old_value"], r["new_value"]) for r in reversed(rows) if r["field"] == "status"]


# ----- 동작: 이름 → 요청 -----
ACTIONS = {
    "edit": lambda c, po: c.patch(f"{URL}/{po['id']}", json={"memo": "x"}),  # 수정
    "approve": lambda c, po: c.post(f"{URL}/{po['id']}/approve"),  # 승인
    "order": lambda c, po: c.post(f"{URL}/{po['id']}/order"),  # 주문 완료 표시
    "email": lambda c, po: c.post(f"{URL}/{po['id']}/email", json={"intro": "안녕하세요."}),  # 메일 발송 (resend 없음)
    "receive": lambda c, po: receive(c, po, 1),  # 입고 1개 (부분)
    "cancel": lambda c, po: c.post(f"{URL}/{po['id']}/cancel", json={"reason": "공급업체 사정"}),  # 취소 (사유 있음)
    "document": lambda c, po: c.get(f"{URL}/{po['id']}/document"),  # 문서 보기 (읽기)
    "document_xlsx": lambda c, po: c.get(f"{URL}/{po['id']}/document.xlsx"),  # 엑셀 (읽기)
    "email_preview": lambda c, po: c.get(f"{URL}/{po['id']}/email"),  # 메일 미리보기 (읽기)
}

INVALID = (409, "INVALID_STATUS")  # 상태가 안 맞을 때 공통 거절. details = {"status": 현재 상태}
# 동작 → {허용 상태: (HTTP, 성공 뒤 상태)}. 여기 없는 상태는 INVALID 로 거절된다 (아래 OTHER 는 예외).
ALLOWED = {
    "edit": {"DRAFT": (200, "DRAFT")},
    "approve": {"DRAFT": (200, "APPROVED")},  # 관리자만. 담당자는 모든 상태에서 403 (아래 별도)
    "order": {"APPROVED": (200, "ORDERED")},
    "email": {"APPROVED": (200, "ORDERED")},  # 표 밖 전이 (po_mail.py)
    "receive": {"ORDERED": (201, "ORDERED")},  # 1/100 이라 부분 입고 → ORDERED 유지
    "cancel": {s: (200, "CANCELLED") for s in ("DRAFT", "APPROVED", "ORDERED")},
    "document": {s: (200, s) for s in ("APPROVED", "ORDERED", "RECEIVED")},
    "document_xlsx": {s: (200, s) for s in ("APPROVED", "ORDERED", "RECEIVED")},
    "email_preview": {s: (200, s) for s in ("APPROVED", "ORDERED")},
}
# INVALID_STATUS 가 아닌 다른 코드로 거절되는 칸 (동작, 상태) → (HTTP, 코드, details)
OTHER = {
    ("email", "ORDERED"): (409, "ALREADY_ORDERED", {"emailed_at": None, "emailed_to": None}),  # 주문 완료 표시로 온 ORDERED (메일 기록 없음)
}


def cells():
    """(상태, 동작, 역할) 칸 목록. 승인은 두 역할 × 5상태, 나머지는 담당자 × 5상태 + 관리자는 허용 상태 하나."""
    out = []
    for action in ACTIONS:
        for state in STATES:
            out.append((state, action, "staff"))
            if action == "approve":
                out.append((state, action, "admin"))
        if action != "approve":
            out.append((next(iter(ALLOWED[action])), action, "admin"))  # 관리자도 같은 결과인지 대표 칸 하나
    return out


@pytest.mark.parametrize("state,action,role", [pytest.param(*c, id="-".join(c)) for c in cells()])
def test_state_action_matrix(client, world, product, state, action, role):
    """상태 × 동작 × 역할 한 칸: 허용이면 응답 코드와 바뀐 상태, 거절이면 (HTTP, 코드, details) 와 상태 그대로."""
    po = make_po(client, world, product, state)
    login_as(client, EMAILS[role])
    r = ACTIONS[action](client, po)
    if action == "approve" and role == "staff":  # 권한 검사가 상태 검사보다 먼저 (모든 상태에서 403)
        assert error(r) == (403, "FORBIDDEN_ROLE", None)
        assert status_of(client, po) == state
    elif state in ALLOWED[action]:
        code, after = ALLOWED[action][state]
        assert r.status_code == code, r.json() if r.headers["content-type"].startswith("application/json") else r.status_code
        if action != "document_xlsx":  # 엑셀은 파일이라 상태 칸이 없다
            assert r.json()["data"]["status"] == after
        assert status_of(client, po) == after
    else:
        expected = OTHER.get((action, state), (*INVALID, {"status": state}))
        assert error(r) == expected
        assert status_of(client, po) == state  # 거절되면 상태는 그대로


# ----- 입고 정정 (stock.py): 정정할 입고가 있는 상태는 ORDERED(부분 입고)·RECEIVED 뿐 -----
@pytest.mark.parametrize("role", ["staff", "admin"])
def test_receipt_correction_allowed_when_ordered(client, world, product, role):
    """ORDERED 에서 부분 입고 40 을 정정하면 201, 누적 입고 30, 상태는 ORDERED 그대로."""
    po = make_po(client, world, product, "ORDERED", received=40)
    login_as(client, EMAILS[role])
    r = client.post(f"/api/v1/inventory-movements/{receipt_movement_id(client)}/corrections",
                    json={"quantity": 10, "reason": "오입력"})
    assert r.status_code == 201, r.json()
    after = client.get(f"{URL}/{po['id']}").json()["data"]
    assert after["status"] == "ORDERED" and after["items"][0]["received_quantity"] == 30


@pytest.mark.parametrize("role", ["staff", "admin"])
def test_receipt_correction_blocked_when_received(client, world, product, role):
    """RECEIVED 가 되면 입고 정정이 막힌다 (마지막 입고를 잘못 넣으면 되돌릴 길이 없다)."""
    # 현재 동작 고정(이슈 #259: RECEIVED 정정 불가, 다음 할 일 안내 없음)
    po = make_po(client, world, product, "RECEIVED")
    login_as(client, EMAILS[role])
    r = client.post(f"/api/v1/inventory-movements/{receipt_movement_id(client)}/corrections",
                    json={"quantity": 1, "reason": "오입력"})
    assert error(r) == (409, "INVALID_STATUS", {"status": "RECEIVED"})
    assert status_of(client, po) == "RECEIVED"


# ----- 취소 특수 칸 -----
def test_cancel_ordered_without_reason_is_422(client, world, product):
    """입고 없는 ORDERED 를 사유 없이 취소하면 422 (사유 필수)."""
    po = make_po(client, world, product, "ORDERED")
    r = client.post(f"{URL}/{po['id']}/cancel")
    assert error(r) == (422, "VALIDATION_ERROR", [{"field": "reason", "reason": "required"}])
    assert status_of(client, po) == "ORDERED"


@pytest.mark.parametrize("body", [None, {"reason": "공급업체 사정"}], ids=["no-reason", "with-reason"])
def test_cancel_after_partial_receipt_is_blocked(client, world, product, body):
    """부분 입고가 있으면 사유 유무와 상관없이 409 CANNOT_CANCEL_RECEIVED (입고 검사가 사유 검사보다 먼저, details 없음)."""
    # 현재 동작 고정(이슈 #252: 잔량 마감 없음)
    po = make_po(client, world, product, "ORDERED", received=40)
    r = client.post(f"{URL}/{po['id']}/cancel", json=body) if body else client.post(f"{URL}/{po['id']}/cancel")
    assert error(r) == (409, "CANNOT_CANCEL_RECEIVED", None)
    assert status_of(client, po) == "ORDERED"


def test_cancel_blocked_even_after_full_correction(client, world, product):
    """입고 40 을 전부 정정해 누적 입고가 0 이어도 취소는 막힌다."""
    # 현재 동작 고정(이슈 #252: 잔량 마감 없음)
    po = make_po(client, world, product, "ORDERED", received=40)
    r = client.post(f"/api/v1/inventory-movements/{receipt_movement_id(client)}/corrections",
                    json={"quantity": 40, "reason": "전부 오입력"})
    assert r.status_code == 201
    assert client.get(f"{URL}/{po['id']}").json()["data"]["items"][0]["received_quantity"] == 0
    r = client.post(f"{URL}/{po['id']}/cancel", json={"reason": "취소"})
    assert error(r) == (409, "CANNOT_CANCEL_RECEIVED", None)
    assert status_of(client, po) == "ORDERED"


# ----- 입고 특수 칸 -----
def test_partial_receipt_keeps_ordered_then_full_makes_received(client, world, product):
    """40 입고 → ORDERED 유지, 나머지 60 입고 → RECEIVED (표 밖 전이, purchase_orders.py)."""
    po = make_po(client, world, product, "ORDERED", received=40)
    assert po["status"] == "ORDERED"
    r = receive(client, po, 60)
    assert r.status_code == 201 and r.json()["data"]["status"] == "RECEIVED"


def test_over_receipt_is_blocked(client, world, product):
    """누적 40 에서 61 을 더 받으면 409 OVER_RECEIPT, details 에 남은 수량."""
    po = make_po(client, world, product, "ORDERED", received=40)
    r = receive(client, po, 61)
    assert error(r) == (409, "OVER_RECEIPT", {"purchase_order_item_id": po["items"][0]["id"], "ordered": 100,
                                               "received": 40, "remaining": 60, "requested": 61})
    assert status_of(client, po) == "ORDERED"


# ----- 메일 특수 칸 -----
def test_email_resend_keeps_ordered(client, world, product, outbox):
    """메일로 ORDERED 가 된 뒤: resend 없으면 409 ALREADY_ORDERED, resend=true 면 200 이고 상태는 ORDERED 그대로."""
    po = make_po(client, world, product, "APPROVED")
    assert ACTIONS["email"](client, po).status_code == 200
    r = ACTIONS["email"](client, po)
    status, code, details = error(r)
    assert (status, code) == (409, "ALREADY_ORDERED") and details["emailed_to"] == "sales@a-supplier.test"
    r = client.post(f"{URL}/{po['id']}/email", json={"intro": "다시 보냅니다.", "resend": True})
    assert r.status_code == 200 and r.json()["data"]["status"] == "ORDERED"
    assert len(outbox) == 2  # 첫 발송 + 다시 보내기


def test_email_failure_keeps_approved(client, world, product, monkeypatch):
    """메일 서버 오류면 502 MAIL_FAILED 이고 APPROVED 그대로."""
    po = make_po(client, world, product, "APPROVED")

    def broken(msg):
        raise smtplib.SMTPServerDisconnected("down")
    monkeypatch.setattr(po_mail, "deliver", broken)
    r = ACTIONS["email"](client, po)
    assert error(r) == (502, "MAIL_FAILED", {"failure_code": "CONNECTION"})
    assert status_of(client, po) == "APPROVED"


# ----- 승인 특수 칸 -----
def test_approve_blocked_by_inactive_product(client, world, product, session):
    """DRAFT 에 비활성 품목이 있으면 승인은 409 INACTIVE_REFERENCE."""
    po = make_po(client, world, product, "DRAFT")
    product.is_active = False
    session.commit()
    login_as(client, "admin@a.test")
    r = ACTIONS["approve"](client, po)
    assert error(r) == (409, "INACTIVE_REFERENCE", [{"field": "items", "reason": "inactive"}])
    assert status_of(client, po) == "DRAFT"


# ----- 작성 특수 칸: 공급업체당 DRAFT 1장 -----
def test_duplicate_draft_then_new_draft_after_approve(client, world, product):
    """같은 공급업체에 DRAFT 가 있으면 409 DUPLICATE_DRAFT, 그 발주서를 APPROVED 로 만들면 새 DRAFT 를 만들 수 있다."""
    # 현재 동작 고정(이슈 #251)
    po = make_po(client, world, product, "DRAFT")
    body = {"supplier_id": world["a_supplier"].id, "items": [{"product_id": product.id, "quantity": 1, "unit_price": 1}]}
    r = client.post(URL, json=body)
    assert error(r) == (409, "DUPLICATE_DRAFT", {"purchase_order_id": po["id"], "po_number": po["po_number"]})
    login_as(client, "admin@a.test")
    assert ACTIONS["approve"](client, po).status_code == 200
    r = client.post(URL, json=body)
    assert r.status_code == 201 and r.json()["data"]["status"] == "DRAFT"


# ----- 변경 이력: status 행의 이전·이후 값 (표 밖 전이 2곳 포함) -----
def test_change_log_status_rows_order_and_receive(client, world, product):
    """승인 → 주문 완료 → 부분 입고 → 나머지 입고: status 행 3개 (부분 입고는 행이 없다, 입고 완료는 표 밖 전이)."""
    po = make_po(client, world, product, "ORDERED", received=40)
    receive(client, po, 60)
    assert status_changes(client, po) == [("DRAFT", "APPROVED"), ("APPROVED", "ORDERED"), ("ORDERED", "RECEIVED")]


def test_change_log_status_rows_email(client, world, product):
    """메일 첫 발송으로 APPROVED → ORDERED 행 (표 밖 전이), 다시 보내기는 행이 없다."""
    po = make_po(client, world, product, "APPROVED")
    ACTIONS["email"](client, po)
    client.post(f"{URL}/{po['id']}/email", json={"intro": "다시", "resend": True})
    assert status_changes(client, po) == [("DRAFT", "APPROVED"), ("APPROVED", "ORDERED")]


def test_change_log_status_rows_cancel(client, world, product):
    """ORDERED 취소: 마지막 status 행이 ORDERED → CANCELLED."""
    po = make_po(client, world, product, "ORDERED")
    ACTIONS["cancel"](client, po)
    assert status_changes(client, po)[-1] == ("ORDERED", "CANCELLED")
