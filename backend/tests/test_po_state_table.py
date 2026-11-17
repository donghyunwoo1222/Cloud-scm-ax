"""발주서 상태 표 테스트 (#260 PR2): 상태 대입은 set_status 한 곳뿐이고, 표가 실제 동작(PR1 행렬)과 맞는지 본다.

DB 가 필요 없는 테스트다(코드 글자와 표만 본다).
"""

import inspect  # set_status 의 소스 글자 읽기
import re  # 상태 대입 찾기 정규식
from pathlib import Path  # app 폴더의 .py 파일 목록

from app.services import purchase_orders as po_service  # set_status
from app.services.po_states import ACTION_STATES, TRANSITIONS  # 검사할 표 2개
from tests.test_po_transitions import (
    ALLOWED,  # PR1 의 허용 행렬 (이 파일은 고치지 않고 값만 읽는다)
)

APP = Path(__file__).resolve().parents[1] / "app"  # backend/app

# 어떤 변수든 X.status = … 또는 X.status, X.ordered_at = … (튜플 대입). == 비교는 제외.
# self.status 는 제외: errors.py 의 AppError.status 는 HTTP 코드이고 발주서 상태가 아니다.
ASSIGN = re.compile(r"\b(?!self\b)\w+\.status\s*(?:,[^=\n]*)?=(?!=)")
# 키워드·setattr 로 넣는 경우: PurchaseOrder(status="…"), .values(status="…"), setattr(order, "status", …)
KEYWORD = re.compile(r"[(,\s]status\s*=\s*[\"']|setattr\(\s*\w+\s*,\s*[\"']status")


def status_writes() -> list[tuple[str, str]]:
    """app 아래 모든 .py 에서 상태 대입으로 보이는 줄 → [(파일 이름, 줄 글자)]."""
    hits = []
    for path in sorted(APP.rglob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]  # 주석은 빼고 본다
            if ASSIGN.search(code) or KEYWORD.search(code):
                hits.append((path.name, line.strip()))
    return hits


def test_status_is_assigned_only_in_set_status():
    """발주서 status 를 바꾸는 줄은 purchase_orders.set_status 안의 한 줄뿐이다."""
    # 정규식 자체 점검: 튜플 대입·키워드는 잡고, 비교·self 는 안 잡는다
    for caught in ('order.status, order.ordered_at = "ORDERED", func.now()', "po.status = target",
                   'PurchaseOrder(company_id=1, status="ORDERED")', 'setattr(order, "status", "X")'):
        assert ASSIGN.search(caught) or KEYWORD.search(caught), caught
    for ignored in ('PurchaseOrder.status == "DRAFT"', 'order.status != "ORDERED"', "self.status = status",
                    'po_link = "/purchase-orders?status="', '{"status": order.status}'):
        assert not (ASSIGN.search(ignored) or KEYWORD.search(ignored)), ignored

    assert status_writes() == [("purchase_orders.py", "order.status = target  # 한 단계만 바꾼다")]
    assert "order.status = target" in inspect.getsource(po_service.set_status)  # 그 한 줄이 set_status 안에 있다


def test_transitions_match_matrix():
    """PR1 행렬에서 상태가 바뀌는 칸 ↔ TRANSITIONS 가 양쪽으로 같다. 입고 완료는 행렬 밖이라 따로 본다."""
    changed = {(action, before, after) for action, cells in ALLOWED.items()
               for before, (_, after) in cells.items() if after != before}  # (동작, 전, 후)
    from_table = {(action, before, target) for action, (sources, target) in TRANSITIONS.items()
                  if action != "complete_receipt" for before in sources}
    assert changed == from_table
    # 입고 완료: test_partial_receipt_keeps_ordered_then_full_makes_received 가 고정한 ORDERED → RECEIVED
    assert TRANSITIONS["complete_receipt"] == ({"ORDERED"}, "RECEIVED")


def test_action_states_keep_old_values():
    """ACTION_STATES 는 PR2 전에 각 파일에 박혀 있던 값과 같고, PR1 행렬의 허용 상태와도 같다."""
    assert ACTION_STATES == {
        "edit": ("DRAFT",),  # purchase_orders.update_order: status != "DRAFT"
        "email": ("APPROVED", "ORDERED"),  # po_mail.MAIL_STATUSES
        "receive": ("ORDERED",),  # purchase_orders.receive_order: status != "ORDERED"
        "correct_receipt": ("ORDERED",),  # stock.create_correction: status != "ORDERED"
        "document": ("APPROVED", "ORDERED", "RECEIVED"),  # po_document.DOCUMENT_STATUSES
    }
    for action, matrix_action in (("edit", "edit"), ("email", "email_preview"), ("receive", "receive"),
                                  ("document", "document"), ("document", "document_xlsx")):
        assert set(ACTION_STATES[action]) == set(ALLOWED[matrix_action]), action
