"""규모 측정 (#184 PR 2): 품목 3,000개 규모에서 주요 API의 서버 처리 시간을 잰다. 서버 코드는 바꾸지 않는다.

실행 방법과 주의는 perf/README.md. 요약:
  - scm_test 에서만 돈다 (DB 이름이 정확히 scm_test 가 아니면 아무것도 하지 않고 멈춘다).
  - 측정용 회사 2곳(이름이 "__perf__"로 시작)을 만들고, 끝나면(실패해도 finally) 그 회사들의 행만 지운다.
  - 측정하는 동안 다른 곳에서 pytest 를 돌리지 않는다 (pytest 는 시작할 때 scm_test 의 표를 모두 지우고 다시 만든다).
  - 이 파일은 tests/ 밖이라 CI 의 pytest 에 들어가지 않는다.
"""

import csv
import io
import json
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import delete, event, func, make_url, select, text
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.clock import seoul_today
from app.config import settings
from app.db import engine
from app.main import app
from app.models import (
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

PREFIX = "__perf__"  # 측정용 회사 이름 접두사 (이 이름의 회사만 지운다)
PASSWORD = "perf-password-1"  # 측정용 사용자 비밀번호 (scm_test 안에서만 쓰고 끝나면 지운다)
N_PRODUCTS_X, N_SUPPLIERS_X, N_PRODUCTS_Y = 3000, 40, 600  # 회사 X(측정 대상) 품목·업체, 회사 Y(다른 회사 섞기) 품목
N_ORDERS_X = 1500  # 회사 X 의 과거 발주서 수 (발주서 목록과 created_at 인덱스 판단용)
SLOW_SECONDS = 2.0  # 이 시간을 넘으면 "느림" (사용자 결정)
READ_RUNS, WRITE_RUNS = 5, 3  # 읽기는 5회(첫 번째는 워밍업), 쓰기는 3회
TABLES = (Company, User, Supplier, Product, PurchaseOrder, PurchaseOrderItem, InventoryMovement, IdempotencyKey, PoChangeLog)


def guard() -> None:
    """DB 이름이 scm_test 또는 scm_test_<이름>(pytest 와 같은 규칙, #211)이 아니면 멈춘다. 표가 없으면 안내하고 멈춘다 (표를 만들거나 지우는 코드는 쓰지 않는다)."""
    name = make_url(settings.database_url).database
    if name is None or re.fullmatch(r"scm_test(_[a-z0-9_]+)?", name) is None:  # tests/conftest.py 의 is_test_db_name 과 같은 규칙
        sys.exit(f"DB 이름이 scm_test 또는 scm_test_<이름> 이 아닙니다({name!r}). 아무것도 하지 않고 멈춥니다.")
    with engine.connect() as conn:
        if conn.scalar(text("SELECT to_regclass('public.inventory_movements')")) is None:
            sys.exit(f"{name} 에 표가 없습니다. 그 DB 를 TEST_DATABASE_URL 로 pytest 를 한 번 돌려 표를 만든 뒤 다시 실행하세요.")


def row_counts() -> dict[str, int]:
    """표별 행 수 (정리 확인용)."""
    with Session(engine) as s:
        return {m.__tablename__: s.scalar(select(func.count()).select_from(m)) for m in TABLES}


def cleanup() -> None:
    """측정용 회사(이름이 PREFIX 로 시작)와 그 회사의 모든 행만 지운다. 다른 회사는 건드리지 않는다."""
    with Session(engine) as s:
        ids = list(s.scalars(select(Company.id).where(Company.name.like(f"{PREFIX}%"))))
        if not ids:
            return
        for model in (IdempotencyKey, InventoryMovement, PoChangeLog, PurchaseOrderItem, PurchaseOrder, Product, Supplier, User):  # 가리키는 쪽부터 (변경 이력은 발주서보다 먼저, #181)
            s.execute(delete(model).where(model.company_id.in_(ids)))
        s.execute(delete(Company).where(Company.id.in_(ids)))
        s.commit()


def load_company(s: Session, tag: str, n_products: int, n_suppliers: int, n_orders: int) -> dict:
    """회사 하나의 가짜 데이터를 SQL 한 번씩으로 만든다. 재고 = 이력 합계 규칙을 지키도록 최초 입고량을 계산해 넣는다."""
    today = seoul_today()
    company = Company(name=f"{PREFIX}{tag}")
    s.add(company)
    s.flush()
    admin = User(company_id=company.id, name="관리자", email=f"admin-{tag}@perf.test".lower(), role="ADMIN",
                 password_hash=hash_password(PASSWORD))
    s.add(admin)
    s.add(User(company_id=company.id, name="담당자", email=f"staff-{tag}@perf.test".lower(), role="STAFF",
               password_hash=admin.password_hash))
    suppliers = [Supplier(company_id=company.id, name=f"업체{i:02d}", lead_time_days=3 + i % 5) for i in range(n_suppliers)]
    s.add_all(suppliers)
    s.flush()
    sup_ids = [x.id for x in suppliers]
    p = {"c": company.id, "n": n_products, "sups": sup_ids, "nsup": len(sup_ids), "u": admin.id, "today": today, "tag": tag}
    s.execute(text(  # 품목: SKU PF-<번호>, 기본 공급업체는 번호 순환
        "INSERT INTO products (company_id, sku, name, unit, unit_cost, safety_stock, default_supplier_id, is_active) "
        "SELECT :c, 'PF-' || i, '품목 ' || i, '개', 1000, 20, (:sups)[1 + i % :nsup], true FROM generate_series(1, :n) AS i"), p)
    # 이력: 판매 90줄(최근 90일), 중간 입고 8줄, 폐기 1줄, 그리고 최초 입고 1줄(100일 전) = 품목당 100줄
    base = ("WITH pp AS (SELECT id, regexp_replace(sku, '\\D', '', 'g')::int AS i FROM products WHERE company_id = :c) ")
    s.execute(text(
        "INSERT INTO inventory_movements (company_id, product_id, movement_type, direction, quantity, movement_date, sales_channel, created_by) "
        + base +
        "SELECT :c, id, 'SALE', 'OUT', 1 + (i * 7 + k * 3) % 3, CAST(:today AS date) - ((i + k * 37) % 90), 'OWN_MALL', :u "
        "FROM pp CROSS JOIN generate_series(1, 90) AS k "
        "UNION ALL "
        "SELECT :c, id, 'RECEIPT', 'IN', 2 + i % 5, CAST(:today AS date) - (10 + (i + k * 11) % 80), NULL, :u "
        "FROM pp CROSS JOIN generate_series(1, 8) AS k "
        "UNION ALL "
        "SELECT :c, id, 'DISPOSAL', 'OUT', 1, CAST(:today AS date) - 5, NULL, :u FROM pp"), p)
    # 목표 재고: 짝수 번호는 0~10(부족 후보 약 50%), 7로 나눠 1 남는 번호는 5,000 이상(과잉 후보), 나머지는 50~200
    target = "CASE WHEN i % 2 = 0 THEN i % 11 WHEN i % 7 = 1 THEN 5000 + i ELSE 50 + i % 151 END"
    s.execute(text(
        "INSERT INTO inventory_movements (company_id, product_id, movement_type, direction, quantity, movement_date, created_by) "
        + base +
        "SELECT :c, pp.id, 'RECEIPT', 'IN', m.net_out + " + target + ", CAST(:today AS date) - 100, :u "
        "FROM pp JOIN (SELECT product_id, SUM(CASE WHEN direction = 'OUT' THEN quantity ELSE -quantity END) AS net_out "
        "FROM inventory_movements WHERE company_id = :c GROUP BY product_id) m ON m.product_id = pp.id"), p)
    if n_orders:  # 과거 발주서(RECEIVED·CANCELLED 만, 재고·추천에 영향 없음) 3줄씩
        s.execute(text(
            "INSERT INTO purchase_orders (company_id, supplier_id, po_number, status, created_by, created_at) "
            "SELECT :c, (:sups)[1 + n % :nsup], 'PO-PERF-' || n, CASE WHEN n % 3 = 0 THEN 'CANCELLED' ELSE 'RECEIVED' END, :u, "
            "now() - (n || ' minutes')::interval FROM generate_series(1, :orders) AS n"), {**p, "orders": n_orders})
        s.execute(text(
            "INSERT INTO purchase_order_items (company_id, purchase_order_id, product_id, quantity, unit_price) "
            "SELECT :c, o.id, pr.id, 10, 1000 FROM purchase_orders o CROSS JOIN generate_series(0, 2) AS j "
            "JOIN LATERAL (SELECT id FROM products WHERE company_id = :c ORDER BY id OFFSET ((regexp_replace(o.po_number, '\\D', '', 'g')::int * 3 + j) % :n) LIMIT 1) pr ON true "
            "WHERE o.company_id = :c"), p)
    s.flush()
    return {"company_id": company.id, "staff_email": f"staff-{tag}@perf.test".lower(), "supplier_ids": sup_ids}


def verify_stock(s: Session, company_id: int, n_products: int) -> None:
    """삽입 검증: 품목별 현재고(이력 합계)가 음수인 품목이 0개이고, 목표 재고와 어긋난 품목도 0개여야 한다. 아니면 측정하지 않는다."""
    row = s.execute(text(
        "WITH st AS (SELECT p.id, regexp_replace(p.sku, '\\D', '', 'g')::int AS i, "
        "COALESCE(SUM(CASE WHEN m.direction = 'IN' THEN m.quantity ELSE -m.quantity END), 0) AS stock "
        "FROM products p LEFT JOIN inventory_movements m ON m.product_id = p.id WHERE p.company_id = :c GROUP BY p.id, p.sku) "
        "SELECT count(*), count(*) FILTER (WHERE stock < 0), "
        "count(*) FILTER (WHERE stock <> CASE WHEN i % 2 = 0 THEN i % 11 WHEN i % 7 = 1 THEN 5000 + i ELSE 50 + i % 151 END) FROM st"),
        {"c": company_id}).one()
    if row[0] != n_products or row[1] != 0 or row[2] != 0:
        sys.exit(f"가짜 데이터 검증 실패(품목 {row[0]}개, 음수 재고 {row[1]}개, 목표와 다른 재고 {row[2]}개). 측정하지 않습니다.")


@dataclass
class Result:
    name: str
    scale: str
    runs: int
    queries: int
    warmup: float
    median: float
    maximum: float
    statuses: set = field(default_factory=set)
    slow_statements: list = field(default_factory=list)  # (초, SQL, 파라미터) 느린 순


class Recorder:
    """SQLAlchemy 이벤트로 호출 한 번의 쿼리 수와 문장별 시간을 모은다."""

    def __init__(self):
        self.current: list | None = None
        event.listen(engine, "before_cursor_execute", self.before)
        event.listen(engine, "after_cursor_execute", self.after)

    def before(self, conn, cursor, statement, parameters, context, executemany):
        if self.current is not None:
            context._perf_start = time.perf_counter()

    def after(self, conn, cursor, statement, parameters, context, executemany):
        if self.current is not None:
            self.current.append((time.perf_counter() - getattr(context, "_perf_start", time.perf_counter()), statement,
                                 None if executemany else parameters))


recorder = Recorder()


def timed(call):
    """호출 한 번: (걸린 초, 응답, 실행한 SQL 목록)."""
    recorder.current = []
    start = time.perf_counter()
    response = call()
    seconds = time.perf_counter() - start
    statements, recorder.current = recorder.current, None
    return seconds, response, statements


def measure(name, scale, call, runs, results, expect=(200, 201), after=None):
    """같은 호출을 runs 번 한다. 첫 번째는 워밍업으로 따로 두고, 중앙값·최댓값은 나머지로 낸다. call(i)는 i번째 호출.

    after 는 호출이 끝난 뒤(시간 재기 밖에서) 측정용 데이터를 되돌리는 함수다."""
    times, statuses, statements_all = [], set(), []
    for i in range(runs):
        seconds, response, statements = timed(lambda i=i: call(i))
        times.append(seconds)
        statuses.add(response.status_code)
        statements_all.append(statements)
        if after:
            after()  # 시간에 넣지 않는다
        if response.status_code not in expect:
            print(f"  경고: {name} 응답 {response.status_code} {response.text[:200]}")
    rest = times[1:] or times
    slowest = sorted((x for x in statements_all[-1]), key=lambda x: -x[0])[:3]
    result = Result(name, scale, runs, len(statements_all[-1]), times[0], statistics.median(rest), max(rest), statuses, slowest)
    results.append(result)
    flag = "느림" if result.median > SLOW_SECONDS or result.maximum > SLOW_SECONDS else "-"
    print(f"  {name:<40} 쿼리 {result.queries:>5}  워밍업 {result.warmup:6.2f}s  중앙값 {result.median:6.2f}s  최댓값 {result.maximum:6.2f}s  {flag}")
    return result


def explain(statement: str, parameters) -> str:
    """읽기 문장(SELECT)만 EXPLAIN (ANALYZE, BUFFERS) 로 본다. 읽기 전용 트랜잭션 안에서 실행하고 되돌린다."""
    if not statement.lstrip().upper().startswith(("SELECT", "WITH")):
        return "(SELECT 가 아니라 EXPLAIN 하지 않음)"
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            rows = conn.exec_driver_sql("EXPLAIN (ANALYZE, BUFFERS) " + statement, parameters).all()
            return "\n".join(r[0] for r in rows)
        except Exception as e:  # noqa: BLE001 - 설명을 못 얻어도 측정은 계속한다
            return f"(EXPLAIN 실패: {type(e).__name__})"
        finally:
            trans.rollback()


def sales_csv(skus: list[str], run: str, day) -> bytes:
    """판매 파일 5,000행: 주문번호, SKU, 수량, 날짜. 재고가 충분한 품목만 쓰고 주문번호는 실행마다 다르다."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["주문번호", "SKU", "수량", "날짜"])
    for n in range(5000):
        w.writerow([f"PERF-{run}-{n}", skus[n % len(skus)], 1, day.isoformat()])
    return out.getvalue().encode("utf-8")


def main(explain_all: bool = False) -> None:
    guard()
    cleanup()  # 이전 실행이 남긴 측정 회사를 먼저 정리
    before = row_counts()
    print(f"[시작 행 수] {before}")
    results: list[Result] = []
    explains: dict[str, list[tuple[float, str]]] = {}
    try:
        t0 = time.perf_counter()
        with Session(engine) as s:
            x = load_company(s, "x", N_PRODUCTS_X, N_SUPPLIERS_X, N_ORDERS_X)
            y = load_company(s, "y", N_PRODUCTS_Y, 8, 0)  # 다른 회사 데이터를 섞는다 (측정은 X 로만)
            s.commit()
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:  # 통계 갱신: 실제 운영처럼 플래너가 행 수를 알게 한다
            for table in ("products", "inventory_movements", "purchase_orders", "purchase_order_items", "suppliers"):
                conn.exec_driver_sql(f"ANALYZE {table}")
        with Session(engine) as s:
            verify_stock(s, x["company_id"], N_PRODUCTS_X)
            verify_stock(s, y["company_id"], N_PRODUCTS_Y)
            n_mov = s.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == x["company_id"]))
            n_mov_y = s.scalar(select(func.count()).select_from(InventoryMovement).where(InventoryMovement.company_id == y["company_id"]))
        scale = f"품목 {N_PRODUCTS_X:,}·이력 {n_mov:,}"
        print(f"[데이터] 회사 X: 품목 {N_PRODUCTS_X:,}, 업체 {N_SUPPLIERS_X}, 이력 {n_mov:,}, 발주서 {N_ORDERS_X:,} / 회사 Y: 품목 {N_PRODUCTS_Y}, 이력 {n_mov_y:,} (만드는 데 {time.perf_counter() - t0:.1f}초, 재고 검증 통과)")

        with TestClient(app) as client:
            r = client.post("/api/v1/auth/login", json={"email": x["staff_email"], "password": PASSWORD})
            assert r.status_code == 200, r.text
            get = lambda path: (lambda i: client.get(f"/api/v1{path}"))
            print("[읽기 측정] 첫 번째 호출은 워밍업")
            for name, path in (
                ("재고 현황 1쪽(20개)", "/stock?page_size=20"),
                ("재고 현황 100개 쪽", "/stock?page_size=100"),
                ("재고 현황 마지막 쪽", "/stock?page_size=20&page=150"),
                ("재고 현황 검색 q", "/stock?q=PF-12&page_size=20"),
                ("재고 상태 필터 SHORTAGE", "/stock?status=SHORTAGE&page_size=100"),
                ("재고 상태 필터 NORMAL", "/stock?status=NORMAL&page_size=100"),
                ("발주 추천", "/recommendations"),
                ("대시보드", "/dashboard"),
                ("품목 목록 1쪽", "/products?page_size=20"),
                ("품목 목록 기본 공급업체 필터", f"/products?default_supplier_id={x['supplier_ids'][0]}&page_size=100"),
                ("발주서 목록 1쪽", "/purchase-orders?page_size=20"),
                ("입출고 이력 1쪽", "/inventory-movements?page_size=20"),
                ("입출고 이력 SALE+기간", f"/inventory-movements?movement_type=SALE&date_from={(seoul_today() - timedelta(days=30)).isoformat()}&page_size=20"),
            ):
                res = measure(name, scale, get(path), READ_RUNS, results)
                if explain_all or res.median > SLOW_SECONDS or name in (
                    "품목 목록 1쪽", "품목 목록 기본 공급업체 필터", "발주서 목록 1쪽", "입출고 이력 SALE+기간", "발주 추천"):
                    explains[name] = [(sec, f"{sql}\n--- 파라미터: {params}\n{explain(sql, params)}") for sec, sql, params in res.slow_statements[:2]]

            # 판매 가져오기: 미리보기(읽기)는 확정 전에 5회, 확정은 쓰기라 뒤에서 3회
            safe_skus = [f"PF-{i}" for i in range(1, N_PRODUCTS_X + 1) if i % 2 == 1 and i % 7 != 1]  # 목표 재고 50 이상인 품목만
            opts = json.dumps({"product_col": 1, "quantity_col": 2, "date_col": 3, "ref_col": 0, "sales_channel": "OWN_MALL"})
            day = seoul_today() - timedelta(days=1)
            preview_file = sales_csv(safe_skus, "PREVIEW", day)
            post_file = lambda path, content: client.post(f"/api/v1{path}", files={"file": ("sales.csv", content, "text/csv")}, data={"options": opts})
            measure("판매 가져오기 미리보기(5,000행)", scale, lambda i: post_file("/sales-imports/preview", preview_file), READ_RUNS, results)

            print("[쓰기 측정] 입력은 매번 다르게, 반복 사이에 측정용 초안은 지운다")
            recs = client.get("/api/v1/recommendations").json()["data"]["items"]
            recs.sort(key=lambda it: it["product_id"])
            print(f"  (추천 대상 {len(recs):,}개)")

            def drop_drafts():  # 측정용 초안만 지운다 (회사 X 의 DRAFT)
                with Session(engine) as s:
                    ids = select(PurchaseOrder.id).where(PurchaseOrder.company_id == x["company_id"], PurchaseOrder.status == "DRAFT")
                    s.execute(delete(PoChangeLog).where(PoChangeLog.purchase_order_id.in_(ids)))  # 초안 변경 이력(#181)이 발주서를 가리키므로 먼저
                    s.execute(delete(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id.in_(ids)))
                    s.execute(delete(PurchaseOrder).where(PurchaseOrder.company_id == x["company_id"], PurchaseOrder.status == "DRAFT"))
                    s.commit()

            if len(recs) >= 1000 + 2 * 100:
                def make_drafts(i):
                    window = recs[i * 100: i * 100 + 1000]  # 반복마다 시작 위치를 100씩 옮긴다
                    return client.post("/api/v1/recommendations/drafts", json={"items": [
                        {"product_id": it["product_id"], "quantity": it["recommended_order_units"]} for it in window]})
                measure("추천 → 초안 1,000품목", f"추천 대상 {len(recs):,}", make_drafts, WRITE_RUNS, results, after=drop_drafts)
            else:
                print(f"  추천 대상이 {len(recs)}개라 1,000품목 초안 측정을 건너뜁니다 (확인 못함)")
            with Session(engine) as s:
                product_ids = list(s.scalars(select(Product.id).where(Product.company_id == x["company_id"]).order_by(Product.id).limit(2000)))

            def make_po(i):
                return client.post("/api/v1/purchase-orders", json={"supplier_id": x["supplier_ids"][i], "items": [
                    {"product_id": pid, "quantity": 1 + i, "unit_price": 1000 + i} for pid in product_ids]})
            measure("발주서 2,000줄 저장", f"품목 {N_PRODUCTS_X:,}", make_po, WRITE_RUNS, results, after=drop_drafts)
            measure("판매 가져오기 확정(5,000행)", scale, lambda i: post_file("/sales-imports", sales_csv(safe_skus, f"RUN{i}", day)), WRITE_RUNS, results)
    finally:
        cleanup()  # 실패해도 측정용 회사만 지운다
        after = row_counts()
        print(f"[정리 후 행 수] {after}")
        print("시작과 같음" if after == before else f"시작과 다름! 시작 {before}")

    print("\n## 결과 표 (워밍업 제외 중앙값·최댓값)")
    print("| 대상 | 데이터 규모 | 쿼리 수 | 워밍업 | 중앙값 | 최댓값 | 2초 초과 | 응답 코드 |")
    print("| --- | --- | ---: | ---: | ---: | ---: | --- | --- |")
    for r in results:
        slow = "초과" if r.median > SLOW_SECONDS or r.maximum > SLOW_SECONDS else "아니오"
        print(f"| {r.name} | {r.scale} | {r.queries} | {r.warmup:.2f}s | {r.median:.2f}s | {r.maximum:.2f}s | {slow} | {sorted(r.statuses)} |")
    print("\n## 가장 오래 걸린 SQL (대상별 상위 문장)")
    for r in results:
        if r.slow_statements:
            print(f"\n### {r.name}")
            for sec, sql, _ in r.slow_statements:
                print(f"- {sec * 1000:.0f}ms: {' '.join(sql.split())[:300]}")
    for name, items in explains.items():
        print(f"\n## EXPLAIN: {name}")
        for sec, text_ in items:
            print(f"\n(문장 {sec * 1000:.0f}ms)\n```\n{text_[:6000]}\n```")


N_RECEIPT_NEW = 100  # 입고 가져오기 측정: 실행마다 새 품목 100개(각 1행) + 기존 품목 4,900행


def receipt_csv(run: str, day) -> bytes:
    """입고 파일 5,000행: 번호, SKU, 품목명, 단위, 단가, 수량, 입고일. 번호와 새 SKU 는 실행마다 다르다."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["입고번호", "SKU", "품목명", "단위", "단가", "수량", "입고일"])
    for n in range(5000 - N_RECEIPT_NEW):
        w.writerow([f"PERF-R-{run}-{n}", f"PF-{1 + n % N_PRODUCTS_X}", "", "", "", 1 + n % 5, day.isoformat()])
    for n in range(N_RECEIPT_NEW):
        w.writerow([f"PERF-RN-{run}-{n}", f"PFN-{run}-{n}", f"새 품목 {n}", "개", 1000, 3, day.isoformat()])
    return out.getvalue().encode("utf-8")


def main_receipt_import() -> None:
    """--only receipt-import (#222): 입고 가져오기 확정 5,000행만 잰다. 품목 3,000개만 만들고 과거 이력은 넣지 않는다.

    전체 측정은 이력 약 37만 건을 만들어 끝의 정리 DELETE 가 약 25분 걸린다. 이 모드는 이력이 측정으로 생긴 1만 5천 건뿐이라 정리가 짧다.
    """
    guard()
    cleanup()
    before = row_counts()
    print(f"[시작 행 수] {before}")
    results: list[Result] = []
    try:
        with Session(engine) as s:
            company = Company(name=f"{PREFIX}receipt")
            s.add(company)
            s.flush()
            s.add(User(company_id=company.id, name="담당자", email="staff-receipt@perf.test", role="STAFF",
                       password_hash=hash_password(PASSWORD)))
            supplier = Supplier(company_id=company.id, name="업체", lead_time_days=3)
            s.add(supplier)
            s.flush()
            s.execute(text(  # 기존 품목: SKU PF-<번호> (전체 측정과 같은 이름 규칙)
                "INSERT INTO products (company_id, sku, name, unit, unit_cost, safety_stock, default_supplier_id, is_active) "
                "SELECT :c, 'PF-' || i, '품목 ' || i, '개', 1000, 20, :s, true FROM generate_series(1, :n) AS i"),
                {"c": company.id, "s": supplier.id, "n": N_PRODUCTS_X})
            s.commit()
            supplier_id = supplier.id
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql("ANALYZE products")
        opts = json.dumps({"ref_col": 0, "product_col": 1, "name_col": 2, "unit_col": 3, "cost_col": 4, "quantity_col": 5,
                           "date_col": 6, "default_supplier_id": supplier_id})
        day = seoul_today() - timedelta(days=1)
        with TestClient(app) as client:
            r = client.post("/api/v1/auth/login", json={"email": "staff-receipt@perf.test", "password": PASSWORD})
            assert r.status_code == 200, r.text
            measure(f"입고 가져오기 확정(5,000행, 새 품목 {N_RECEIPT_NEW})", f"품목 {N_PRODUCTS_X:,}", lambda i: client.post(
                "/api/v1/receipt-imports", files={"file": ("receipt.csv", receipt_csv(f"RUN{i}", day), "text/csv")},
                data={"options": opts}), WRITE_RUNS, results)
    finally:
        t0 = time.perf_counter()
        cleanup()
        after = row_counts()
        print(f"[정리 후 행 수] {after} (정리 {time.perf_counter() - t0:.1f}초)")
        print("시작과 같음" if after == before else f"시작과 다름! 시작 {before}")
    print("\n| 대상 | 데이터 규모 | 쿼리 수 | 워밍업 | 중앙값 | 최댓값 | 응답 코드 |")
    print("| --- | --- | ---: | ---: | ---: | ---: | --- |")
    for r in results:
        print(f"| {r.name} | {r.scale} | {r.queries} | {r.warmup:.2f}s | {r.median:.2f}s | {r.maximum:.2f}s | {sorted(r.statuses)} |")


if __name__ == "__main__":
    if "--only" in sys.argv:  # 지금은 receipt-import 하나만 있다
        if sys.argv[sys.argv.index("--only") + 1:][:1] != ["receipt-import"]:
            sys.exit("--only 뒤에는 receipt-import 만 쓸 수 있습니다.")
        main_receipt_import()
    else:
        main(explain_all="--explain-all" in sys.argv)
