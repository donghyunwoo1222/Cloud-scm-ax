"""독촉 동작(remind, #269)의 상태 5 × 역할 2 행렬. test_po_transitions.py 의 PR1 행렬은 고치지 않고 이 파일에서 따로 본다.

모든 상태의 발주서를 납기가 지난 날짜로 맞춘 뒤: 버튼(allowed_actions)은 ORDERED 에만 있고, 서버도 ORDERED 만 받는다.
"""

from datetime import timedelta  # 지난 납기

import pytest  # 테스트 도구

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import PurchaseOrder  # 납기를 직접 맞춘다 (테스트 준비만)
from app.services.po_states import allowed_actions  # 순수 함수
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_reminder import outbox  # noqa: F401  가짜 메일 서버 + 독촉 켜짐 (pytest 픽스처)
from tests.test_po_transitions import (  # 준비 도구 (읽기만)
    STATES,
    URL,
    make_po,
    product,  # noqa: F401 (pytest 픽스처로 쓴다)
)

ROLES = {"STAFF": "staff@a.test", "ADMIN": "admin@a.test"}


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("state", STATES)
def test_remind_only_for_overdue_ordered(client, session, world, product, outbox, state, role):  # noqa: F811
    po = make_po(client, world, product, state)
    order = session.get(PurchaseOrder, po["id"])
    order.due_date = seoul_today() - timedelta(days=3)  # 모든 상태를 "납기 지남"으로
    session.commit()
    login_as(client, ROLES[role])
    shown = "remind" in client.get(f"{URL}/{po['id']}").json()["data"]["allowed_actions"]
    r = client.post(f"{URL}/{po['id']}/reminder", json={"intro": "확인 부탁드립니다."})
    if state == "ORDERED":
        assert shown and r.status_code == 200 and len(outbox) == 1  # 역할 무관
    else:
        assert not shown and (r.status_code, r.json()["error"]["code"]) == (409, "INVALID_STATUS")
        assert r.json()["error"]["details"] == {"status": state} and outbox == []


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("state", STATES)
def test_allowed_actions_overdue_flag(state, role):
    for receipts in (False, True):
        without = allowed_actions(state, role, receipts)
        with_flag = allowed_actions(state, role, receipts, overdue=True)
        assert "remind" not in without  # 기본값 False: 기존 결과 그대로
        assert with_flag == ([*without[:without.index("email") + 1], "remind", *without[without.index("email") + 1:]]
                             if state == "ORDERED" else without)  # ORDERED 에만, 메일 보내기 바로 뒤
