"""발주서 변경 이력 (#181) 테스트: DRAFT 수정·상태 변경이 po_change_log 에 남는지, 롤백·회사 분리·추가 전용·멱등 키·대량 줄."""

from types import SimpleNamespace  # 로그인 대신 넣을 간단한 값 묶음

import pytest  # 테스트 도구
from fastapi.testclient import TestClient  # 진짜 DB 세션을 쓰는 별도 클라이언트
from sqlalchemy import event, func, select  # 쿼리 기록, 개수 세기
from sqlalchemy.orm import Session  # 요청마다 새 세션

from app.auth.deps import get_current_user  # 로그인 사용자 의존성
from app.config import settings  # SMTP 설정 (테스트 동안만 바꾼다)
from app.db import get_db  # 앱이 쓰는 DB 세션 의존성
from app.main import app  # 테스트할 앱
from app.models import InventoryMovement, PoChangeLog, PurchaseOrder, Supplier  # 표
from app.schemas.purchase_orders import PurchaseOrderCreate  # 발주서 작성 요청 모양
from app.services import po_mail  # 바꿔 끼울 발송 함수
from app.services import purchase_orders as po_service  # 이력 함수를 바꿔 끼울 곳
from tests.concurrency import run_in_new_session  # 진짜 commit 하는 새 세션
from tests.helpers import login_as  # 공통 로그인
from tests.test_recommendations import add_product, stock_50_sold_300  # 준비 도구
from tests.test_scale_limits import bulk_products, recommended_products  # 대량 준비 도구

PO = "/api/v1/purchase-orders"  # 발주 경로
DRAFTS = "/api/v1/recommendations/drafts"  # 추천 초안 경로


def make_draft(client, session, world, skus=("P1", "P2"), **fields):
    """회사 A 담당자로 DRAFT 한 장(품목마다 100개·단가 800)을 만든다 → (응답 data, 품목들). 새 발주서 생성은 이력을 남기지 않는다."""
    products = [add_product(session, world, sku) for sku in skus]
    session.commit()
    login_as(client)
    body = {"supplier_id": world["a_supplier"].id, "due_date": "2026-11-30", "memo": "처음 메모",
            "delivery_address": "서울 본사", "payment_terms": "현금",
            "items": [{"product_id": p.id, "quantity": 100, "unit_price": 800} for p in products], **fields}
    r = client.post(PO, json=body)
    assert r.status_code == 201, r.json()
    return r.json()["data"], products


def logs(session, order_id):
    """이 발주서의 이력 행들 (오래된 순)."""
    return list(session.scalars(select(PoChangeLog).where(PoChangeLog.purchase_order_id == order_id).order_by(PoChangeLog.id)))


def trio(rows):
    return [(r.field, r.old_value, r.new_value) for r in rows]  # (항목, 전, 후)


def same_items(products, quantity=100, unit_price=800):
    return [{"product_id": p.id, "quantity": quantity, "unit_price": unit_price} for p in products]


def to_ordered(client, order):
    """DRAFT → 승인(관리자) → 발주함(담당자)."""
    login_as(client, "admin@a.test")
    assert client.post(f"{PO}/{order['id']}/approve").status_code == 200
    login_as(client)
    assert client.post(f"{PO}/{order['id']}/order").status_code == 200


# ----- DRAFT 수정: 헤더 4칸 -----
@pytest.mark.parametrize("field,new,old", [
    ("due_date", "2026-12-01", "2026-11-30"),
    ("memo", "새 메모", "처음 메모"),
    ("delivery_address", "부산 지점", "서울 본사"),
    ("payment_terms", "30일 후", "현금"),
])
def test_header_field_change_logged(client, world, session, field, new, old):
    order, _ = make_draft(client, session, world)
    assert logs(session, order["id"]) == []  # 새 발주서 생성은 기록하지 않는다
    assert client.patch(f"{PO}/{order['id']}", json={field: new}).status_code == 200
    [row] = logs(session, order["id"])
    assert (row.field, row.old_value, row.new_value) == (field, old, new)
    assert row.changed_by == world["a_staff"].id and row.company_id == world["a_company"].id and row.reason is None


def test_clearing_header_fields_logs_null(client, world, session):
    order, _ = make_draft(client, session, world)
    assert client.patch(f"{PO}/{order['id']}", json={"memo": None, "delivery_address": ""}).status_code == 200
    assert sorted(trio(logs(session, order["id"])), key=str) == sorted(
        [("delivery_address", "서울 본사", None), ("memo", "처음 메모", None)], key=str)


def test_same_values_patch_creates_no_rows(client, world, session):
    order, products = make_draft(client, session, world)
    r = client.patch(f"{PO}/{order['id']}", json={
        "memo": "처음 메모", "due_date": "2026-11-30", "delivery_address": "서울 본사", "payment_terms": "현금",
        "items": same_items(products)})
    assert r.status_code == 200
    assert logs(session, order["id"]) == []  # 값이 같은 칸은 행을 만들지 않는다


# ----- DRAFT 수정: 줄 수량 변경·추가·삭제 -----
def test_line_change_add_delete_logged_with_previous_values(client, world, session):
    order, (p1, _p2) = make_draft(client, session, world)
    p3 = add_product(session, world, "P3")
    session.commit()
    items = [{"product_id": p1.id, "quantity": 120, "unit_price": 800},  # P1 수량 변경
             {"product_id": p3.id, "quantity": 5, "unit_price": 1000}]  # P3 추가, P2 는 빠짐(삭제)
    r = client.patch(f"{PO}/{order['id']}", json={"items": items, "memo": "같이 바꾼 메모"})
    assert r.status_code == 200, r.json()
    assert sorted(trio(logs(session, order["id"])), key=str) == sorted([
        ("items[P1].quantity", "100", "120"),
        ("items[P2]", "수량 100 · 단가 800원", None),  # 삭제 직전 값이 남는다
        ("items[P3]", None, "수량 5 · 단가 1,000원"),
        ("memo", "처음 메모", "같이 바꾼 메모"),
    ], key=str)


def test_box_line_deletion_keeps_box_info(client, world, session):
    p1 = add_product(session, world, "B1", units_per_box=10, box_unit_cost=9000, order_unit="박스")
    p2 = add_product(session, world, "B2")
    session.commit()
    login_as(client)
    r = client.post(PO, json={"supplier_id": world["a_supplier"].id, "items": [
        {"product_id": p1.id, "box_quantity": 3}, {"product_id": p2.id, "quantity": 5, "unit_price": 100}]})
    assert r.status_code == 201, r.json()
    order = r.json()["data"]
    assert client.patch(f"{PO}/{order['id']}", json={"items": same_items([p2], 5, 100)}).status_code == 200
    [row] = logs(session, order["id"])
    assert row.field == "items[B1]" and row.new_value is None
    assert "수량 30" in row.old_value and "박스 10개입" in row.old_value and "박스단가 9,000원" in row.old_value


# ----- 상태 변경 -----
def test_status_changes_logged_with_actor(client, world, session):
    order, _ = make_draft(client, session, world)
    login_as(client, "admin@a.test")
    client.post(f"{PO}/{order['id']}/approve")
    login_as(client)
    client.post(f"{PO}/{order['id']}/order")
    full = [{"purchase_order_item_id": i["id"], "quantity": 100} for i in order["items"]]
    assert client.post(f"{PO}/{order['id']}/receipts", json={"items": full}).status_code == 201  # 전량 입고 → RECEIVED
    rows = logs(session, order["id"])
    assert [(r.field, r.old_value, r.new_value, r.changed_by) for r in rows] == [
        ("status", "DRAFT", "APPROVED", world["a_admin"].id),
        ("status", "APPROVED", "ORDERED", world["a_staff"].id),
        ("status", "ORDERED", "RECEIVED", world["a_staff"].id),
    ]


def test_partial_receipt_logs_nothing(client, world, session):
    order, _ = make_draft(client, session, world)
    to_ordered(client, order)
    r = client.post(f"{PO}/{order['id']}/receipts", json={"items": [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 10}]})
    assert r.status_code == 201
    assert [r.new_value for r in logs(session, order["id"])] == ["APPROVED", "ORDERED"]  # 부분 입고는 ORDERED 그대로라 새 행이 없다


@pytest.fixture
def outbox(monkeypatch):
    """가짜 메일 서버: 실제로 보내지 않고 보낸 메일을 목록에 담는다."""
    sent = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.test")
    monkeypatch.setattr(settings, "smtp_from", "noreply@scm.test")
    monkeypatch.setattr(po_mail, "deliver", sent.append)
    return sent


def test_mail_path_logs_ordered(client, world, session, outbox):
    world["a_supplier"].email = "sales@a-supplier.test"
    order, _ = make_draft(client, session, world)
    login_as(client, "admin@a.test")
    assert client.post(f"{PO}/{order['id']}/approve").status_code == 200
    r = client.post(f"{PO}/{order['id']}/email", json={"intro": "발주 드립니다."})
    assert r.status_code == 200, r.json()
    assert len(outbox) == 1
    last = logs(session, order["id"])[-1]
    assert (last.field, last.old_value, last.new_value, last.changed_by) == ("status", "APPROVED", "ORDERED", world["a_admin"].id)
    assert client.post(f"{PO}/{order['id']}/email", json={"intro": "다시", "resend": True}).status_code == 200
    assert len(logs(session, order["id"])) == 2  # 다시 보내기는 상태가 안 바뀌므로 행이 늘지 않는다


# ----- 추천 초안 -----
def test_recommendation_draft_adds_lines_logged_but_new_draft_not(client, world, session):
    p1, p2 = stock_50_sold_300(session, world, "D1"), stock_50_sold_300(session, world, "D2")
    session.commit()
    login_as(client)
    first = client.post(DRAFTS, json={"items": [{"product_id": p1.id, "quantity": 150}]})
    assert first.status_code == 201, first.json()
    order_id = first.json()["data"][0]["id"]
    assert logs(session, order_id) == []  # 새 DRAFT 생성은 기록하지 않는다
    second = client.post(DRAFTS, json={"items": [{"product_id": p2.id, "quantity": 160}]})
    assert second.status_code == 201 and second.json()["data"][0]["created"] is False
    [row] = logs(session, order_id)
    assert (row.field, row.old_value, row.new_value, row.changed_by) == ("items[D2]", None, "수량 160 · 단가 1,000원", world["a_staff"].id)


# ----- 취소 사유 -----
@pytest.mark.parametrize("stage", ["DRAFT", "APPROVED"])
def test_cancel_before_order_needs_no_reason(client, world, session, stage):
    order, _ = make_draft(client, session, world)
    if stage == "APPROVED":
        login_as(client, "admin@a.test")
        client.post(f"{PO}/{order['id']}/approve")
    assert client.post(f"{PO}/{order['id']}/cancel").status_code == 200  # 본문 없이
    last = logs(session, order["id"])[-1]
    assert (last.field, last.old_value, last.new_value, last.reason) == ("status", stage, "CANCELLED", None)


def test_cancel_reason_saved_and_trimmed(client, world, session):
    order, _ = make_draft(client, session, world)
    assert client.post(f"{PO}/{order['id']}/cancel", json={"reason": "  거래처 요청  "}).status_code == 200
    assert logs(session, order["id"])[-1].reason == "거래처 요청"


def test_cancel_ordered_requires_reason(client, world, session):
    order, _ = make_draft(client, session, world)
    to_ordered(client, order)
    before = len(logs(session, order["id"]))
    for body in ({}, {"reason": None}, {"reason": "   "}):  # 없음·null·공백
        r = client.post(f"{PO}/{order['id']}/cancel", json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR", body
    assert client.post(f"{PO}/{order['id']}/cancel").status_code == 422  # 본문 자체가 없어도
    assert client.post(f"{PO}/{order['id']}/cancel", json={"reason": "가" * 501}).status_code == 422  # 500자 초과
    assert client.get(f"{PO}/{order['id']}").json()["data"]["status"] == "ORDERED"  # 아무것도 안 바뀜
    assert len(logs(session, order["id"])) == before
    assert client.post(f"{PO}/{order['id']}/cancel", json={"reason": "가" * 500}).status_code == 200  # 경계: 500자 통과
    last = logs(session, order["id"])[-1]
    assert (last.old_value, last.new_value, last.reason) == ("ORDERED", "CANCELLED", "가" * 500)


# ----- 조회 API -----
def test_change_log_api_latest_first_names_only_and_count(client, world, session):
    order, _ = make_draft(client, session, world)
    client.patch(f"{PO}/{order['id']}", json={"memo": "1차"})
    client.patch(f"{PO}/{order['id']}", json={"memo": "2차"})
    r = client.get(f"{PO}/{order['id']}/change-log")
    assert r.status_code == 200
    body = r.json()
    assert [row["new_value"] for row in body["data"]] == ["2차", "1차"]  # 최신순
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 2}  # 개수는 정확히
    assert set(body["data"][0]) == {"id", "field", "old_value", "new_value", "changed_by_name", "reason", "created_at"}
    assert body["data"][0]["changed_by_name"] == "a-STAFF"
    assert "@" not in r.text  # 이메일 비노출
    assert client.get(f"{PO}/{order['id']}/change-log", params={"page_size": 1, "page": 2}).json()["data"][0]["new_value"] == "1차"


def test_change_log_other_company_is_404(client, world, session):
    order, _ = make_draft(client, session, world)
    client.patch(f"{PO}/{order['id']}", json={"memo": "변경"})
    login_as(client, "admin@b.test")
    assert client.get(f"{PO}/{order['id']}/change-log").status_code == 404
    assert client.get(f"{PO}/999999/change-log").status_code == 404


def test_no_route_can_modify_or_delete_logs():
    routes = [r for r in app.routes if "change-log" in getattr(r, "path", "")]
    assert [(r.path, sorted(r.methods)) for r in routes] == [("/api/v1/purchase-orders/{order_id}/change-log", ["GET"])]


def test_modify_methods_rejected(client, world, session):
    order, _ = make_draft(client, session, world)
    client.patch(f"{PO}/{order['id']}", json={"memo": "변경"})
    row_id = logs(session, order["id"])[0].id
    for path in (f"{PO}/{order['id']}/change-log", f"{PO}/{order['id']}/change-log/{row_id}"):
        for method in ("post", "put", "patch", "delete"):
            assert getattr(client, method)(path).status_code in (404, 405), (method, path)
    assert len(logs(session, order["id"])) == 1


# ----- 이력 저장과 변경은 한 트랜잭션 -----
@pytest.mark.parametrize("action", ["patch", "approve"])
def test_failure_after_log_insert_rolls_back_change(engine, committed_company, monkeypatch, action):
    """이력을 넣고 변경을 DB 로 보낸(flush) 뒤 예외가 나면, 별도 연결에서 봐도 변경도 이력도 없다."""
    data = committed_company
    supplier_id = run_in_new_session(engine, lambda s: s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
    request = PurchaseOrderCreate(supplier_id=supplier_id, memo="처음", items=[{"product_id": data["product_id"], "quantity": 10, "unit_price": 100}])
    order_id = run_in_new_session(engine, lambda s: po_service.create_order(data["company_id"], s, data["admin_id"], request).id)
    real_log = po_service.log_change

    def log_then_fail(db, *args, **kwargs):
        real_log(db, *args, **kwargs)  # 이력 행은 실제로 넣고
        db.flush()  # 변경도 DB 로 보낸 뒤
        raise RuntimeError("이력 저장 뒤 강제 오류")

    monkeypatch.setattr(po_service, "log_change", log_then_fail)

    def real_db():  # 앱의 get_db 와 같은 모양: 요청마다 새 세션 (테스트 DB 로)
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_db] = real_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=data["admin_id"], company_id=data["company_id"], role="ADMIN", is_active=True)
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.patch(f"{PO}/{order_id}", json={"memo": "바뀐 메모"}) if action == "patch" else c.post(f"{PO}/{order_id}/approve")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 500
    state = run_in_new_session(engine, lambda s: (
        s.get(PurchaseOrder, order_id).memo, s.get(PurchaseOrder, order_id).status,
        s.scalar(select(func.count()).select_from(PoChangeLog).where(PoChangeLog.company_id == data["company_id"]))))
    assert state == ("처음", "DRAFT", 0)  # 변경도 이력도 남지 않았다


# ----- 멱등 키: 재전송된 입고는 이력을 두 번 쌓지 않는다 -----
def test_idempotent_receipt_does_not_duplicate_log(client, world, session):
    order, _ = make_draft(client, session, world, skus=("P1",))
    to_ordered(client, order)
    body = {"items": [{"purchase_order_item_id": order["items"][0]["id"], "quantity": 100}]}  # 전량 → RECEIVED
    first = client.post(f"{PO}/{order['id']}/receipts", json=body, headers={"Idempotency-Key": "k-181"})
    second = client.post(f"{PO}/{order['id']}/receipts", json=body, headers={"Idempotency-Key": "k-181"})
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert [r.new_value for r in logs(session, order["id"])] == ["APPROVED", "ORDERED", "RECEIVED"]  # RECEIVED 는 한 번
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == 1


# ----- 줄이 많아도 이력 INSERT 는 한 번 (줄마다 INSERT 하지 않는다) -----
def record(session, call):
    """call() 이 DB 로 보낸 SQL 문장들을 모아 (문장 목록, 결과) 로 돌려준다."""
    seen = []
    bind = session.get_bind()

    def on_execute(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(bind, "before_cursor_execute", on_execute)
    try:
        return seen, call()
    finally:
        event.remove(bind, "before_cursor_execute", on_execute)


def log_inserts(statements):
    return sum(1 for s in statements if s.lstrip().upper().startswith("INSERT INTO PO_CHANGE_LOG"))


def test_update_1000_lines_log_insert_does_not_grow_with_lines(client, world, session):
    products = bulk_products(session, world, 1000, "UP-")
    session.commit()
    login_as(client)
    r = client.post(PO, json={"supplier_id": world["a_supplier"].id, "items": same_items(products, 1, 100)})
    assert r.status_code == 201
    order_id = r.json()["data"]["id"]

    def patch(changed, quantity):  # 앞의 changed 줄만 수량을 바꾸고 나머지는 지금 값 그대로
        items = [{"product_id": p.id, "quantity": quantity if i < changed else 1, "unit_price": 100} for i, p in enumerate(products)]
        return lambda: client.patch(f"{PO}/{order_id}", json={"items": items})

    small, r1 = record(session, patch(100, 2))
    big, r2 = record(session, patch(1000, 3))
    assert r1.status_code == r2.status_code == 200
    assert len(logs(session, order_id)) == 100 + 1000  # 첫 PATCH 100행, 둘째 1000행
    print(f"\n[수정 쿼리 수] 100줄 변경: 전체 {len(small)}, 이력 INSERT {log_inserts(small)} / 1000줄 변경: 전체 {len(big)}, 이력 INSERT {log_inserts(big)}")
    assert log_inserts(small) == log_inserts(big) == 1  # 100행이든 1000행이든 INSERT 한 번
    assert len(big) <= len(small) + 3  # 줄 수에 비례해 쿼리가 늘지 않는다


def test_recommendation_draft_1000_lines_log_insert_does_not_grow(client, world, session):
    products = recommended_products(session, world, 1101, "DR-")
    session.commit()
    login_as(client)

    def add(chunk):
        return lambda: client.post(DRAFTS, json={"items": [{"product_id": p.id, "quantity": 160} for p in chunk]})

    assert client.post(DRAFTS, json={"items": [{"product_id": products[0].id, "quantity": 160}]}).status_code == 201  # 처음 1줄로 DRAFT 생성
    small, r1 = record(session, add(products[1:101]))  # 기존 DRAFT 에 100줄 추가
    big, r2 = record(session, add(products[101:]))  # 1000줄 추가
    assert r1.status_code == r2.status_code == 201, (r1.json(), r2.json())
    assert session.scalar(select(func.count()).select_from(PoChangeLog)) == 1100
    print(f"\n[추천 초안 쿼리 수] 100줄 추가: 전체 {len(small)}, 이력 INSERT {log_inserts(small)} / 1000줄 추가: 전체 {len(big)}, 이력 INSERT {log_inserts(big)}")
    assert log_inserts(small) == log_inserts(big) == 1
    assert len(big) <= len(small) + 3
