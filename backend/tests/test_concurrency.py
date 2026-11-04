"""동시 요청 테스트: 행 잠금으로 '한 줄 세우기'가 되는지 실제 DB 연결 여러 개로 확인한다.

규칙을 지키는 코드가 잠금 없이도 한 번씩은 통과할 수 있으므로, 여러 건을 같은 순간에 보내 겹치게 만든다.
"""

import pytest  # 테스트 도구
from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.errors import AppError  # 업무 오류
from app.models import Company, Product, PurchaseOrder, PurchaseOrderItem, Supplier, User  # 표
from app.schemas.movements import CorrectionCreate  # 정정 요청 모양
from app.schemas.purchase_orders import (  # 발주서 작성·입고 요청 모양
    PurchaseOrderCreate,
    ReceiptCreate,
)
from app.schemas.users import UserUpdate  # 직원 수정 요청 모양
from app.services import purchase_orders as po_service  # 발주서 작성
from app.services import stock as stock_service  # 재고 (register_movement)
from app.services import users as users_service  # 직원 계정 (LAST_ADMIN)
from tests.concurrency import (  # 동시 요청 도구
    delayed,
    delete_companies,
    hold_row_lock,
    run_at_once,
    run_in_new_session,
)


@pytest.fixture
def committed_company(engine):
    """진짜로 commit 한 회사 하나(관리자 1명, 공급업체 1개, 품목 1개). 테스트가 끝나면 지운다."""
    def create(session):
        company = Company(name="동시성상사")
        session.add(company)
        session.flush()  # company.id 생성
        admin = User(company_id=company.id, name="관리자0", email=f"admin0-{company.id}@concurrency.test",
                     password_hash="x", role="ADMIN")  # 로그인은 하지 않으므로 해시는 아무 값
        supplier = Supplier(company_id=company.id, name="동시성업체", lead_time_days=3)
        session.add_all([admin, supplier])
        session.flush()  # id 생성
        product = Product(company_id=company.id, sku="CC-1", name="동시성품목", unit="개", unit_cost=1000,
                          default_supplier_id=supplier.id)
        session.add(product)
        session.commit()  # 진짜 확정 (다른 연결에서도 보인다)
        return {"company_id": company.id, "admin_id": admin.id, "product_id": product.id}

    data = run_in_new_session(engine, create)
    yield data
    delete_companies(engine, [data["company_id"]])  # 테스트 데이터 정리


def sell(engine, data, quantity):
    """새 세션(= 요청 하나)으로 판매 출고를 등록한다."""
    return run_in_new_session(engine, lambda s: stock_service.register_movement(
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="SALE",
        direction="OUT", quantity=quantity, movement_date=seoul_today(), sales_channel="OWN_MALL",
    ))


@pytest.mark.parametrize("requests", [2, 8], ids=["two", "eight"])
def test_concurrent_sales_only_one_succeeds(engine, committed_company, requests):
    """#29 완료 기준: 재고 52개에 30개씩 동시에 보내면 한 건만 성공하고 재고는 22 (음수가 되지 않는다)."""
    data = committed_company
    run_in_new_session(engine, lambda s: stock_service.register_movement(  # 먼저 52개 입고
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="RECEIPT",
        direction="IN", quantity=52, movement_date=seoul_today(),
    ))

    results = run_at_once(*[lambda: sell(engine, data, 30) for _ in range(requests)])  # 30개 출고를 동시에

    successes = [r for r in results if not isinstance(r, Exception)]  # 성공한 요청
    failures = [r for r in results if isinstance(r, Exception)]  # 실패한 요청
    assert len(successes) == 1  # 52 − 30 = 22, 두 번째 30은 들어갈 수 없다
    assert all(isinstance(e, AppError) and e.code == "INSUFFICIENT_STOCK" for e in failures)  # 실패는 모두 재고 부족
    assert successes[0][1] == 22  # 성공한 요청이 본 등록 직후 재고
    final = run_in_new_session(engine, lambda s: stock_service.current_stock(data["company_id"], s, data["product_id"]))
    assert final == 22  # 실제 이력 합계도 22


def test_concurrent_admin_demotions_keep_one_admin(engine, committed_company):
    """#24 LAST_ADMIN: 관리자 5명이 같은 순간 모두 스스로 담당자가 되려 해도 활성 관리자는 1명 남는다."""
    data = committed_company

    def add_admins(session):
        for i in range(1, 5):  # 관리자 4명 더 (총 5명)
            session.add(User(company_id=data["company_id"], name=f"관리자{i}", role="ADMIN", password_hash="x",
                             email=f"admin{i}-{data['company_id']}@concurrency.test"))
        session.commit()
        return list(session.scalars(select(User.id).where(User.company_id == data["company_id"])))

    admin_ids = run_in_new_session(engine, add_admins)  # 5명의 id

    def demote(user_id):
        return run_in_new_session(engine, lambda s: users_service.update_user(
            data["company_id"], s, user_id, UserUpdate(role="STAFF")))

    results = run_at_once(*[lambda uid=uid: demote(uid) for uid in admin_ids])  # 5명이 동시에 내려가기

    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 1  # 마지막 한 명만 막힌다
    assert isinstance(failures[0], AppError) and failures[0].code == "LAST_ADMIN"
    left = run_in_new_session(engine, lambda s: s.scalar(
        select(func.count()).select_from(User).where(User.company_id == data["company_id"], User.role == "ADMIN")))
    assert left == 1  # 관리자가 0명이 되지 않았다


def test_concurrent_corrections_never_exceed_original(engine, committed_company):
    """#30: 판매 10 에 정정 6 두 건을 동시에 보내도 한 건만 성공한다 (정정 합계 12 > 10 이 되지 않는다)."""
    data = committed_company
    run_in_new_session(engine, lambda s: stock_service.register_movement(  # 입고 50
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="RECEIPT",
        direction="IN", quantity=50, movement_date=seoul_today(),
    ))
    sale_id = run_in_new_session(engine, lambda s: stock_service.register_movement(  # 판매 10 → 그 이력 id
        data["company_id"], s, data["admin_id"], product_id=data["product_id"], movement_type="SALE",
        direction="OUT", quantity=10, movement_date=seoul_today(), sales_channel="OWN_MALL",
    )[0].id)  # 세션이 닫히기 전에 id 를 꺼낸다

    def fix(quantity):
        return run_in_new_session(engine, lambda s: stock_service.create_correction(
            data["company_id"], s, data["admin_id"], sale_id, CorrectionCreate(quantity=quantity, reason="오입력")))

    gate = hold_row_lock(engine, Product, data["product_id"])  # 품목 줄을 0.5초 잠가 8건이 확실히 겹치게
    results = run_at_once(gate, *[delayed(lambda: fix(6)) for _ in range(8)])[1:]  # 문지기 결과는 빼고 정정 8건만

    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 7  # 첫 6 이후에는 4 만 남아 6 은 모두 막힌다
    assert all(isinstance(e, AppError) and e.code == "CORRECTION_EXCEEDS" for e in failures)
    total = run_in_new_session(engine, lambda s: stock_service.corrected_quantity(data["company_id"], s, sale_id))
    assert total == 6  # 정정 합계가 원래 수량 10 을 넘지 않았다


def test_concurrent_draft_creation_makes_one_draft(engine, committed_company):
    """#33: 같은 공급업체에 발주서 작성 8건을 동시에 보내도 DRAFT 는 1장, 나머지는 DUPLICATE_DRAFT (회사 행 잠금)."""
    data = committed_company
    supplier_id = run_in_new_session(engine, lambda s: s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
    request = PurchaseOrderCreate(supplier_id=supplier_id, items=[{"product_id": data["product_id"], "quantity": 1, "unit_price": 100}])

    def create():
        return run_in_new_session(engine, lambda s: po_service.create_order(data["company_id"], s, data["admin_id"], request).po_number)

    gate = hold_row_lock(engine, Company, data["company_id"])  # 회사 줄을 0.5초 잠가 8건이 확실히 겹치게
    results = run_at_once(gate, *[delayed(create) for _ in range(8)])[1:]  # 문지기 결과는 빼고 작성 8건만

    failures = [r for r in results if isinstance(r, Exception)]
    assert len(failures) == 7 and all(isinstance(e, AppError) and e.code == "DUPLICATE_DRAFT" for e in failures)
    assert len([r for r in results if isinstance(r, str)]) == 1  # 한 건만 발주번호를 받았다


def committed_draft(engine, data) -> int:
    """진짜로 commit 한 DRAFT 발주서 하나 → id (상태 변경 동시 요청 테스트용)."""
    supplier_id = run_in_new_session(engine, lambda s: s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
    request = PurchaseOrderCreate(supplier_id=supplier_id, items=[{"product_id": data["product_id"], "quantity": 5, "unit_price": 100}])
    return run_in_new_session(engine, lambda s: po_service.create_order(data["company_id"], s, data["admin_id"], request).id)


def status_call(engine, data, order_id, action):
    """상태 변경 한 건을 새 연결로 (API 요청 하나와 같은 모양) → 바뀐 상태."""
    return lambda: run_in_new_session(engine, lambda s: po_service.change_status(data["company_id"], s, data["admin_id"], order_id, action).status)


def test_concurrent_approvals_apply_once(engine, committed_company):
    """#34: 같은 발주서에 승인 8건을 동시에 보내도 1건만 성공, 나머지는 INVALID_STATUS (발주서 행 잠금)."""
    data = committed_company
    order_id = committed_draft(engine, data)
    gate = hold_row_lock(engine, PurchaseOrder, order_id)  # 발주서 줄을 0.5초 잠가 8건이 확실히 겹치게
    results = run_at_once(gate, *[delayed(status_call(engine, data, order_id, "approve")) for _ in range(8)])[1:]
    assert results.count("APPROVED") == 1
    assert all(isinstance(e, AppError) and e.code == "INVALID_STATUS" for e in results if e != "APPROVED")


def test_concurrent_approve_and_cancel_serialized(engine, committed_company):
    """#34: 같은 DRAFT 에 승인 4건·취소 4건을 동시에 보내면 한 줄로 처리된다.

    취소는 APPROVED 에서도 되므로 가능한 결과는 두 가지뿐이다: 취소가 먼저(취소 1건만 성공) 또는 승인 1건 → 취소 1건.
    어느 쪽이든 승인은 많아야 1건, 취소는 정확히 1건, 최종 상태는 CANCELLED. 잠금이 없으면 승인 여러 건이 함께 성공한다.
    """
    data = committed_company
    order_id = committed_draft(engine, data)
    gate = hold_row_lock(engine, PurchaseOrder, order_id)  # 발주서 줄을 0.5초 잠가 8건이 확실히 겹치게
    calls = [status_call(engine, data, order_id, a) for a in ("approve", "cancel") * 4]  # 승인 4건, 취소 4건
    results = run_at_once(gate, *[delayed(c) for c in calls])[1:]
    assert results.count("APPROVED") <= 1 and results.count("CANCELLED") == 1
    assert all(isinstance(e, AppError) and e.code == "INVALID_STATUS" for e in results if not isinstance(e, str))
    assert run_in_new_session(engine, lambda s: s.get(PurchaseOrder, order_id).status) == "CANCELLED"


def ordered_po(engine, data, product_ids, quantity=100) -> tuple[int, list[int]]:
    """진짜로 commit 한 ORDERED 발주서 하나 → (발주서 id, 줄 id 들 = product_ids 순서). 작성 → 승인 → 발주."""
    supplier_id = run_in_new_session(engine, lambda s: s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
    request = PurchaseOrderCreate(supplier_id=supplier_id, items=[{"product_id": p, "quantity": quantity, "unit_price": 100} for p in product_ids])
    order_id = run_in_new_session(engine, lambda s: po_service.create_order(data["company_id"], s, data["admin_id"], request).id)
    for action in ("approve", "order"):
        run_in_new_session(engine, lambda s, a=action: po_service.change_status(data["company_id"], s, data["admin_id"], order_id, a))
    items = run_in_new_session(engine, lambda s: {i.product_id: i.id for i in s.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order_id))})
    return order_id, [items[p] for p in product_ids]


def receive_call(engine, data, order_id, lines):
    """입고 한 건을 새 연결로 (API 요청 하나와 같은 모양) → 바뀐 상태. lines 는 (줄 id, 수량)."""
    body = ReceiptCreate(items=[{"purchase_order_item_id": i, "quantity": q} for i, q in lines])
    return lambda: run_in_new_session(engine, lambda s: po_service.receive_order(data["company_id"], s, data["admin_id"], order_id, body).status)


def test_concurrent_receipts_never_exceed_order(engine, committed_company):
    """#35 완료 기준: 100개 중 70개 입고된 줄에 30개씩 8건을 동시에 보내면 1건만 성공, 나머지는 OVER_RECEIPT (발주서 행 잠금)."""
    data = committed_company
    order_id, (item_id,) = ordered_po(engine, data, [data["product_id"]])
    receive_call(engine, data, order_id, [(item_id, 70)])()  # 먼저 70 입고
    gate = hold_row_lock(engine, PurchaseOrder, order_id)  # 발주서 줄을 0.5초 잠가 8건이 확실히 겹치게
    results = run_at_once(gate, *[delayed(receive_call(engine, data, order_id, [(item_id, 30)])) for _ in range(8)])[1:]
    assert results.count("RECEIVED") == 1  # 30 이 한 번 들어가 100 이 되며 전량 입고
    assert all(isinstance(e, AppError) and e.code in ("OVER_RECEIPT", "INVALID_STATUS") for e in results if e != "RECEIVED")  # 뒤 요청은 초과이거나(RECEIVED 이후) 상태 오류
    total = run_in_new_session(engine, lambda s: po_service.received_quantities(data["company_id"], s, [item_id])[item_id])
    assert total == 100  # 발주 수량을 넘지 않았다


def test_concurrent_receipt_and_cancel_one_wins(engine, committed_company):
    """#35: ORDERED 발주에 입고와 취소를 동시에 보내면 둘 중 하나만 성공한다.

    문지기는 품목 줄을 잠근다. 입고는 상태(ORDERED)를 읽은 뒤 품목 잠금에서 멈추므로, 그 사이에 취소가 끼어들 틈이 생긴다.
    입고가 발주서를 먼저 잠그면 취소는 입고가 끝날 때까지 기다려 409, 잠그지 않으면 둘 다 성공해 이 테스트가 실패한다.
    허용 결과: "입고 성공 + 취소 409 CANNOT_CANCEL_RECEIVED" 또는 "취소 성공 + 입고 409 INVALID_STATUS".
    """
    data = committed_company
    order_id, (item_id,) = ordered_po(engine, data, [data["product_id"]])
    gate = hold_row_lock(engine, Product, data["product_id"])  # 품목 줄을 0.5초 잠가 입고가 '상태 확인 후 쓰기 전'에 멈추게
    cancel = lambda: run_in_new_session(engine, lambda s: po_service.change_status(data["company_id"], s, data["admin_id"], order_id, "cancel").status)
    receipt, cancelled = run_at_once(gate, delayed(receive_call(engine, data, order_id, [(item_id, 10)])), delayed(cancel, 0.2))[1:]  # 입고가 먼저 출발, 취소는 입고가 멈춘 뒤

    def outcome(r):
        return r if isinstance(r, str) else getattr(r, "code", repr(r))  # 성공이면 상태, 실패면 오류 코드

    assert (outcome(receipt), outcome(cancelled)) in (
        ("ORDERED", "CANNOT_CANCEL_RECEIVED"),  # 입고가 이겼다
        ("INVALID_STATUS", "CANCELLED"),  # 취소가 이겼다
    ), (outcome(receipt), outcome(cancelled))


def test_receipts_in_opposite_product_order_do_not_deadlock(engine, committed_company):
    """#35: 품목 A·B 가 든 발주서 두 장에 A→B, B→A 순서로 동시에 입고해도 둘 다 끝난다 (품목 번호 순으로 잠그므로 교착 없음)."""
    data = committed_company
    def add_product_b(s):
        product = Product(company_id=data["company_id"], sku="CC-2", name="동시성품목2", unit="개", unit_cost=1000,
                          default_supplier_id=s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
        s.add(product)
        s.flush()  # id 받기
        return product.id

    product_b = run_in_new_session(engine, add_product_b)  # 두 번째 품목 B
    a = data["product_id"]
    po1, (a1, b1) = ordered_po(engine, data, [a, product_b])
    po2, (a2, b2) = ordered_po(engine, data, [a, product_b])
    for _ in range(5):  # 여러 번 겹쳐 본다 (교착은 운이 나쁠 때만 드러나므로)
        results = run_at_once(
            receive_call(engine, data, po1, [(a1, 1), (b1, 1)]),  # A → B 순서로 보냄
            receive_call(engine, data, po2, [(b2, 1), (a2, 1)]),  # B → A 순서로 보냄
        )
        assert results == ["ORDERED", "ORDERED"], results  # 교착이면 한쪽이 DeadlockDetected 예외가 된다
