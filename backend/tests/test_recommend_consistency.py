"""Codex 교차 검증 반영 (#84) 테스트: 추천 계산이 한 시점으로 읽는지, 초안이 잠근 뒤 계산하는지, N+1, 오늘 판매 포함.

진짜로 commit 하는 테스트는 committed_company(리드타임 3, 안전재고 0)와 committed_products(현재고 0, 일평균 10 → 추천 170)를 쓴다.
"""

import time  # 문지기가 잠근 채 기다리기

import pytest  # 같은 테스트를 여러 경우로
from fastapi.routing import APIRoute  # 앱의 경로 목록
from sqlalchemy import event  # 쿼리 횟수 세기
from sqlalchemy.orm import Session  # 새 연결 세션

from app.api import dashboard, recommendations, stock  # 조회 경로 묶음
from app.db import SNAPSHOT, get_read_db  # 한 시점 읽기 설정과 의존성
from app.errors import AppError  # 업무 오류
from app.models import Product, Supplier  # 표
from app.schemas.purchase_orders import ReceiptCreate  # 발주 입고 요청 모양
from app.services import purchase_orders as po_service  # 발주 입고
from app.services import recommendations as recommendation_service  # 추천 조회·초안
from app.services import stock as stock_service  # 직접 입고
from tests.concurrency import delayed, ordered_po, run_at_once, run_in_new_session  # 동시 요청 도구
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendation_drafts import (  # 추천 대상 품목(170), 초안 요청 한 건
    committed_products,
    draft_call,
)
from tests.test_recommendations import (  # 준비 도구
    TODAY,
    add_move,
    add_product,
    get,
    item,
    stock_50_sold_300,
)

# ----- 1. 한 시점으로 읽기 -----

def test_snapshot_read_does_not_mix_before_and_after_receipt(engine, committed_company, monkeypatch):
    """현재고(0)를 읽은 직후 진행 중 100개가 전량 입고돼도, 한 시점으로 읽으면 가용재고 100 → 추천 없음.

    문장마다 그 순간을 읽으면(READ COMMITTED) 현재고는 입고 전 0, 진행 중은 입고 후 0 이 섞여 추천 170 이 나온다(Codex 재현).
    """
    data = committed_company
    [pid] = committed_products(engine, data, 1)  # 현재고 0, 일평균 10, 재주문점 30
    order_id, [line_id] = ordered_po(engine, data, [pid], quantity=100)  # 진행 중 100 → 가용재고 100 > 30
    original = recommendation_service.in_transit  # 진짜 진행 중 수량 조회

    def receive_then_read(company_id, db):  # 현재고를 읽은 뒤, 진행 중 수량을 읽기 직전에 다른 연결이 전량 입고를 확정한다
        request = ReceiptCreate(items=[{"purchase_order_item_id": line_id, "quantity": 100}])
        run_in_new_session(engine, lambda s: po_service.receive_order(data["company_id"], s, data["admin_id"], order_id, request))
        return original(company_id, db)

    monkeypatch.setattr(recommendation_service, "in_transit", receive_then_read)  # 두 조회 사이에 입고를 끼워 넣는다
    with Session(engine.execution_options(**SNAPSHOT)) as s:  # 앱의 조회 세션과 같은 격리 수준
        result = recommendation_service.list_recommendations(data["company_id"], s, TODAY)
    assert result["items"] == []  # 입고 전(0 + 100)이든 후(100 + 0)든 가용재고 100 → 추천 없음


def test_read_routes_use_snapshot_session():
    """추천·재고·대시보드 조회 경로는 한 시점 세션(get_read_db)을 쓴다."""
    wanted = {"/recommendations", "/stock", "/stock/{product_id}", "/dashboard"}  # 각 라우터 안의 경로 (/api/v1 은 앱이 붙인다)
    found = {
        r.path for router in (recommendations.router, stock.router, dashboard.router) for r in router.routes
        if isinstance(r, APIRoute) and r.path in wanted and "GET" in r.methods
        and get_read_db in {d.call for d in r.dependant.dependencies}  # 이 경로의 의존성에 읽기 세션이 있는지
    }
    assert found == wanted


# ----- 2. 초안 만들기는 잠근 뒤 검사·계산 -----

def receipt_gate(engine, data, pid):
    """문지기: 품목에 직접 입고 100 을 넣고(품목 줄 잠금) 0.5초 뒤 확정."""
    def gate():
        with Session(engine) as s:
            stock_service.register_movement(data["company_id"], s, data["admin_id"], product_id=pid,
                                            movement_type="RECEIPT", direction="IN", quantity=100, movement_date=TODAY)
            time.sleep(0.5)  # 초안 요청이 도착해 기다리는 시간
            s.commit()
    return gate


def deactivate_gate(engine, data, pid):
    """문지기: 품목을 비활성으로 바꾸고(행 잠금) 0.5초 뒤 확정."""
    def gate():
        with Session(engine) as s:
            s.get(Product, pid).is_active = False
            s.flush()  # UPDATE 가 행을 잠근다
            time.sleep(0.5)
            s.commit()
    return gate


@pytest.mark.parametrize("make_gate, code", [
    (receipt_gate, "NOT_RECOMMENDED"),  # 입고 100 → 가용재고 100 > 재주문점 30
    (deactivate_gate, "INACTIVE_REFERENCE"),  # 비활성 품목은 새 발주에 못 넣는다
])
def test_draft_sees_change_committed_during_request(engine, committed_company, make_gate, code):
    """초안 계산 중 그 품목의 입고·비활성이 확정되면 최신 값으로 다시 판단해 409 (예전에는 옛 계산 170 으로 초안이 생겼다)."""
    data = committed_company
    [pid] = committed_products(engine, data, 1)  # 추천 170
    gate = make_gate(engine, data, pid)
    _, result = run_at_once(gate, delayed(draft_call(engine, data, [pid])))  # 문지기가 먼저 잠그고, 초안 요청이 뒤따른다
    assert isinstance(result, AppError) and result.code == code, result


# ----- 3. 초안 만들기 N+1 없음 -----

def test_draft_query_count_same_for_3_and_30_items(client, world, session, engine):
    """품목 3개와 30개로 초안을 만들 때 쿼리 횟수가 같다 (품목마다 따로 묻지 않는다). 둘 다 새 업체라 새 초안을 만든다."""
    def count_queries(n):
        supplier = Supplier(company_id=world["a_company"].id, name=f"N{n}업체", lead_time_days=5)  # 회마다 새 업체 → 같은 경로(새 초안)
        session.add(supplier)
        session.flush()
        ids = [stock_50_sold_300(session, world, f"N{n}-{k}", supplier=supplier).id for k in range(n)]  # 추천 160 품목 n개
        session.commit()
        login_as(client)
        seen = []  # 실행된 SQL
        listener = lambda *args: seen.append(args[2])  # before_cursor_execute 의 SQL 문장을 모은다
        event.listen(engine, "before_cursor_execute", listener)
        try:
            response = client.post("/api/v1/recommendations/drafts", json={"items": [{"product_id": p, "quantity": 160} for p in ids]})
            assert response.status_code == 201, response.json()
        finally:
            event.remove(engine, "before_cursor_execute", listener)
        return len(seen)

    assert count_queries(3) == count_queries(30)


# ----- 4. 최근 30일에 오늘 판매 포함 -----

def test_today_sale_is_counted(client, world, session):
    """오늘 판매 30 만 있는 품목: 30일 판매 30 → 일평균 1, 재주문점 1 × 5 + 20 = 25, 추천 1 × 19 + 20 − 0 = 39."""
    p = add_product(session, world, "TODAY")  # A업체 리드타임 5, 안전재고 20
    add_move(session, world, p, "RECEIPT", "IN", 30, 40)  # 40일 전 입고 30 (데이터 부족 아님)
    add_move(session, world, p, "SALE", "OUT", 30, 0)  # 오늘 판매 30 → 현재고 0
    session.commit()
    row = item(get(client), "TODAY")
    assert row is not None and (row["avg_daily_sales"], row["recommended_quantity"]) == (1.0, 39)
