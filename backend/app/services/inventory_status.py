"""재고 목록·한 건에 부족/정상/판단 불가 상태와 발주 진행 중 수량을 붙인다 (#76, F5).

판정은 추천과 같은 계산(calculate_for → calculate_recommendation → stock_status) 하나만 쓴다. 공식을 여기서 새로 만들지 않는다.
stock.py 에 두지 않은 이유: stock → recommendations → purchase_orders → stock 으로 서로를 불러오는 순환이 생긴다.
읽기만 하고 commit 하지 않는다. 쿼리 횟수는 품목 수와 무관하다.
"""

from datetime import date  # 날짜

from sqlalchemy.orm import Session  # DB 세션 타입

from app.models import Product  # 품목 표
from app.pagination import PageParams  # 쪽 번호·쪽 크기
from app.services.products import list_products  # 품목 목록 (활성 거르기·최신순·쪽 나누기)
from app.services.recommend import (  # 제외 결과 모양, 상태 판정 (추천과 같은 기준)
    Excluded,
    stock_status,
)
from app.services.recommendations import (  # 추천 계산 입력 조회(쿼리 5번), 진행 중 수량
    calculate_for,
    in_transit,
)
from app.services.stock import stock_rows  # 품목들의 현재고 응답 칸
from app.services.tenant import get_owned  # 경로 id 로 우리 회사 품목 찾기 (다른 회사 404)


def status_of(result) -> tuple:
    """계산 결과 하나 → (상태, 판단 불가 이유). 이유는 추천 화면의 제외 목록과 같은 코드·문장이다."""
    reason = {"code": result.code, "message": result.message} if isinstance(result, Excluded) else None  # 판단 불가면 이유
    return stock_status(result), reason


def status_map(company_id: int, db: Session, today: date, product_ids: list[int] | None = None) -> dict[int, tuple]:
    """품목 id → (상태, 판단 불가 이유). 활성 품목만 계산한다(비활성은 추천처럼 계산하지 않아 키가 없다)."""
    return {product.id: status_of(result) for product, *_, result in calculate_for(company_id, db, today, product_ids)}


def with_status(company_id: int, db: Session, today: date, products: list[Product], statuses: dict | None = None) -> list[dict]:
    """현재고 응답 칸에 in_transit·status·status_reason 을 더한다. 비활성 품목은 상태 없음(null)."""
    rows = stock_rows(company_id, db, products)  # 현재고 (한 번의 GROUP BY)
    if statuses is None:  # 미리 계산한 상태가 없으면 이 품목들만 계산
        statuses = status_map(company_id, db, today, [p.id for p in products if p.is_active])
    transit = in_transit(company_id, db)  # 비활성 품목도 진행 중 발주는 있을 수 있어 따로 구한다 (쿼리 2번)
    for row in rows:
        status, reason = statuses.get(row["product_id"], (None, None))  # 비활성이면 (None, None)
        row.update(in_transit=transit.get(row["product_id"], 0), status=status, status_reason=reason)
    return rows


def list_stock(
    company_id: int, db: Session, today: date, page: PageParams, include_inactive: bool, status: str | None,
    *, q: str | None = None,  # 품목명·SKU 검색어는 생략할 수 있다
) -> tuple[list[dict], dict]:
    """GET /stock. 상태 필터가 없으면 지금처럼 DB 가 쪽을 자르고 그 쪽만 계산한다.

    상태 필터가 있으면 검색에 맞는 활성 품목의 상태를 계산해 거른 뒤 최신순으로 쪽을 자른다.
    예) 품목 300개 중 부족 7개 → 1쪽에 7개, total 7. 쪽을 먼저 자르고 거르면 1쪽에 부족이 0개일 수 있다.
    """
    if status is None:
        products, meta = list_products(company_id, db, page, include_inactive, q)  # 검색과 활성 조건으로 거른 뒤 DB가 쪽을 나눈다
        return with_status(company_id, db, today, products), meta
    # shortcut: 검색에 맞는 활성 품목의 상태를 파이썬에서 계산하고 쪽을 나눈다. 수천 개에서 느려지면 계산 결과 저장을 검토한다
    rows = calculate_for(company_id, db, today, q=q)  # 검색이 맞는 활성 품목만 계산한다 (비활성은 상태가 없다)
    statuses = {p.id: status_of(r) for p, *_, r in rows}  # 품목 id → (상태, 이유)
    products = [p for p, *_ in rows if statuses[p.id][0] == status]  # 고른 상태만
    start = (page.page - 1) * page.page_size  # 예) 2쪽, 20개씩 → 20번째부터
    page_products = products[start:start + page.page_size]
    meta = {"page": page.page, "page_size": page.page_size, "total": len(products)}  # 목록 공통 meta 모양
    return with_status(company_id, db, today, page_products, statuses), meta


def get_stock(company_id: int, db: Session, today: date, product_id: int) -> dict:
    """GET /stock/{product_id}: 한 품목 (비활성도 조회 가능, 상태는 null). 다른 회사·없는 id 는 404."""
    product = get_owned(company_id, db, Product, product_id)
    return with_status(company_id, db, today, [product])[0]
