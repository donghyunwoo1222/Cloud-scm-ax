"""슬랙 [확인]·[취소] 동시 클릭 테스트 (#197 PR 5b). 서로 다른 DB 연결(세션)이 실제로 commit 하며 겹친다(tests/concurrency.py 패턴).

본 방어선은 서버의 nonce(idempotency_keys 의 unique 키)다. 슬랙 화면(chat.update)은 이 테스트와 상관없는 보조다.
"""

from datetime import UTC, datetime, timedelta  # 고정 아닌 '지금' (확인 토큰 만료 30분 안)

from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import Company, PurchaseOrder, SlackLink  # 표
from app.services import chat_order as co  # 검사 대상
from app.services import stock as stock_service  # 입출고 등록 (추천 대상 만들기)
from tests.concurrency import delayed, hold_row_lock, run_at_once, run_in_new_session


def prepare(engine, data) -> str:
    """추천 대상 품목(현재고 10, 30일 판매 300, 리드타임 3·안전재고 0이라 재주문점 30)과 슬랙 연결을 commit 하고, 160개짜리 확인 토큰을 돌려준다."""
    day = seoul_today()
    cid, uid, pid = data["company_id"], data["admin_id"], data["product_id"]

    def setup(session):
        stock_service.register_movement(cid, session, uid, product_id=pid, movement_type="RECEIPT", direction="IN", quantity=310,
                                        movement_date=day - timedelta(days=40))
        stock_service.register_movement(cid, session, uid, product_id=pid, movement_type="SALE", direction="OUT", quantity=300,
                                        movement_date=day - timedelta(days=1), sales_channel="OWN_MALL")
        session.add(SlackLink(company_id=cid, user_id=uid, slack_team_id="T0CONC", slack_user_id="U0CONC", linked_at=datetime.now(UTC)))

    run_in_new_session(engine, setup)
    return co._seal({"u": uid, "c": cid, "day": day.isoformat(), "exp": int((datetime.now(UTC) + timedelta(minutes=30)).timestamp()),
                     "nonce": "concurrent-nonce", "items": [[pid, 160, 1]]})


def confirm(engine, data, token):
    return run_in_new_session(engine, lambda s: co.confirm(s, data["company_id"], data["admin_id"], token, seoul_today(), datetime.now(UTC)))


def cancel(engine, data, token):
    return run_in_new_session(engine, lambda s: co.cancel(s, data["company_id"], data["admin_id"], token))


def order_count(engine, data) -> int:
    return run_in_new_session(engine, lambda s: s.scalar(select(func.count()).select_from(PurchaseOrder).where(PurchaseOrder.company_id == data["company_id"])))


def test_double_confirm_makes_one_draft(engine, committed_company):
    data = committed_company
    token = prepare(engine, data)
    gate = hold_row_lock(engine, Company, data["company_id"])  # 회사 줄을 잠가 두 확인이 확실히 겹치게
    results = run_at_once(gate, *[delayed(lambda: confirm(engine, data, token)) for _ in range(2)])[1:]
    assert not any(isinstance(r, Exception) for r in results), results
    assert sorted(r.outcome for r in results) == ["ALREADY_DONE", "OK"]  # 한 번만 만들고 나머지는 이미 처리됨
    assert order_count(engine, data) == 1


def test_confirm_and_cancel_at_once_exactly_one_wins(engine, committed_company):
    data = committed_company
    token = prepare(engine, data)
    gate = hold_row_lock(engine, Company, data["company_id"])
    results = run_at_once(gate, delayed(lambda: confirm(engine, data, token)), delayed(lambda: cancel(engine, data, token)))[1:]
    assert not any(isinstance(r, Exception) for r in results), results
    confirmed, cancelled = results
    if confirmed.outcome == "OK":  # 확인이 이김: 초안 1건, 취소는 이미 처리됨
        assert cancelled.outcome == "ALREADY_DONE" and order_count(engine, data) == 1
    else:  # 취소가 이김: 초안 0건, 확인은 이미 처리됨
        assert (cancelled.outcome, confirmed.outcome) == ("OK", "ALREADY_DONE") and order_count(engine, data) == 0


def test_confirm_and_cancel_without_gate_never_both(engine, committed_company):
    """문지기 없이 그냥 동시에 보내도 '취소했는데 초안이 생기는' 일은 없다. 몇 번 반복해 본다는 한계는 있다(한 번만 시도)."""
    data = committed_company
    token = prepare(engine, data)
    confirmed, cancelled = run_at_once(lambda: confirm(engine, data, token), lambda: cancel(engine, data, token))
    assert not isinstance(confirmed, Exception) and not isinstance(cancelled, Exception), (confirmed, cancelled)
    assert [confirmed.outcome, cancelled.outcome].count("OK") == 1
    assert order_count(engine, data) == (1 if confirmed.outcome == "OK" else 0)
