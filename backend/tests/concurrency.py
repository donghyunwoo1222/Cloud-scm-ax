"""동시 요청 테스트 공통 도구.

보통 테스트는 하나의 트랜잭션 안에서 돌고 끝에 되돌리지만, 동시 요청은 서로 다른 DB 연결이 실제로 commit 해야
잠금(행 잠금)을 확인할 수 있다. 그래서 여기 함수들은 진짜로 commit 하고, 끝나면 만든 회사 데이터를 직접 지운다.
"""

import threading  # 여러 작업을 동시에 실행
import time  # 잠깐 기다리기

from sqlalchemy import delete, select  # DELETE·SELECT 문
from sqlalchemy.orm import Session  # DB 세션

from app.models import (  # 표 9개
    Company,
    IdempotencyKey,
    InventoryMovement,
    PoChangeLog,
    Product,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
    User,
)
from app.schemas.purchase_orders import PurchaseOrderCreate  # 발주서 작성 요청 모양 (ordered_po)
from app.services import purchase_orders as po_service  # 발주서 작성·상태 변경 (ordered_po)


def run_at_once(*calls):
    """함수들을 스레드로 '같은 순간'에 출발시키고 모두 끝날 때까지 기다린다.

    돌려주는 값: 함수마다 결과값, 또는 그 함수가 던진 예외 (순서는 calls 와 같다).
    예) run_at_once(lambda: sell(30), lambda: sell(30)) → [(이력, 22), AppError(INSUFFICIENT_STOCK)]
    """
    barrier = threading.Barrier(len(calls))  # 모든 스레드가 준비될 때까지 출발선에서 기다리게 한다
    results: list = [None] * len(calls)  # 함수별 결과 자리

    def worker(i, call):
        barrier.wait()  # 다 같이 출발
        try:
            results[i] = call()  # 성공하면 결과값
        except Exception as e:  # noqa: BLE001 — 어떤 예외든 그대로 담아 돌려줘야 테스트가 종류를 확인할 수 있다
            results[i] = e

    threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)]  # 함수마다 스레드 하나
    for t in threads:
        t.start()  # 출발 (barrier 에서 서로 기다린다)
    for t in threads:
        t.join(timeout=30)  # 끝날 때까지 기다림 (잠금이 안 풀리면 30초 뒤 실패로 드러나게)
    assert not any(t.is_alive() for t in threads), "동시 실행이 30초 안에 끝나지 않았다 (잠금이 풀리지 않음?)"
    return results


def run_in_new_session(engine, fn):
    """새 DB 연결·세션 하나로 fn(session) 을 실행하고 성공하면 commit 한다. API 요청 하나와 같은 모양.

    fn 이 예외를 던지면 commit 하지 않는다 (세션이 닫히며 되돌려지고 잠금도 풀린다).
    """
    with Session(engine) as session:
        result = fn(session)  # 요청 처리
        session.commit()  # 요청 끝의 확정 (API 계층의 db.commit() 과 같은 자리)
        return result


def delete_companies(engine, company_ids: list[int]) -> None:
    """테스트가 commit 한 회사들과 그 회사의 모든 행을 지운다. 다른 표를 가리키는 표부터 차례로."""
    with Session(engine) as session:
        for model in (IdempotencyKey, InventoryMovement, PoChangeLog, PurchaseOrderItem, PurchaseOrder, Product, Supplier, User):  # 가리키는 쪽부터
            session.execute(delete(model).where(model.company_id.in_(company_ids)))
        session.execute(delete(Company).where(Company.id.in_(company_ids)))  # 마지막에 회사
        session.commit()


def hold_row_lock(engine, model, row_id: int, seconds: float = 0.5):
    """'문지기': 행 하나를 seconds 동안 잠가 두는 함수를 돌려준다. run_at_once 의 첫 함수로 넣는다.

    새 연결을 만드는 시간이 요청마다 달라 '동시' 요청이 실제로는 한 줄로 들어가 버리는 일을 막는다.
    문지기가 잠근 동안 다른 요청들은 모두 출발해 각자 기다리는 자리까지 와 있고, 문지기가 풀면 한꺼번에 겹친다.
    다른 요청은 delayed() 로 감싸 문지기가 먼저 잠그게 한다.
    """
    def gate():
        with Session(engine) as session:
            session.scalar(select(model).where(model.id == row_id).with_for_update())  # 잠금
            time.sleep(seconds)  # 다른 요청들이 모두 도착할 시간
            session.commit()  # 풀기

    return gate


def delayed(call, seconds: float = 0.1):
    """call 을 seconds 뒤에 실행하는 함수로 감싼다 (문지기가 먼저 잠그도록)."""
    def run():
        time.sleep(seconds)
        return call()

    return run


def ordered_po(engine, data, product_ids, quantity=100) -> tuple[int, list[int]]:
    """진짜로 commit 한 ORDERED 발주서 하나 → (발주서 id, 줄 id 들 = product_ids 순서). 작성 → 승인 → 발주."""
    supplier_id = run_in_new_session(engine, lambda s: s.scalar(select(Supplier.id).where(Supplier.company_id == data["company_id"])))
    request = PurchaseOrderCreate(supplier_id=supplier_id, items=[{"product_id": p, "quantity": quantity, "unit_price": 100} for p in product_ids])
    order_id = run_in_new_session(engine, lambda s: po_service.create_order(data["company_id"], s, data["admin_id"], request).id)
    for action in ("approve", "order"):
        run_in_new_session(engine, lambda s, a=action: po_service.change_status(data["company_id"], s, data["admin_id"], order_id, a))
    items = run_in_new_session(engine, lambda s: {i.product_id: i.id for i in s.scalars(select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == order_id))})
    return order_id, [items[p] for p in product_ids]
