"""입출고 등록·정정 경로 (F4). 관리자·담당자 모두 사용. 이력 수정·삭제 경로는 없다(잘못 넣은 건 정정으로)."""

from datetime import date  # 기간 칸
from typing import Annotated, Literal  # 타입에 부가 정보를 붙이는 도구, 정해진 값 중 하나

from fastapi import APIRouter, Query  # 라우터, 쿼리 문자열 칸
from sqlalchemy import func, select  # 이력에 연결된 발주 품목 조회

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.models import InventoryMovement, PurchaseOrderItem  # 발주 품목에 발주서 번호가 있다.
from app.pagination import Page  # page·page_size
from app.schemas.common import PathId, QueryId  # 번호 칸 (DB 범위를 넘으면 422, #71)
from app.schemas.movements import (  # 요청·응답 모양
    CorrectionCreate,
    MovementCreate,
    MovementOut,
    MovementTypeFilter,
)
from app.services import products as products_service  # 품목 조회
from app.services import stock as stock_service  # 재고 업무 규칙

router = APIRouter(prefix="/inventory-movements")  # 이 파일의 경로는 모두 /inventory-movements 로 시작


@router.get("")  # 이력 조회 (읽기만)
def list_movements(
    user: CurrentUser,
    db: DB,
    page: Page,
    product_id: QueryId = None,  # 이 품목만 (비활성 품목의 이력도 볼 수 있다)
    movement_type: Annotated[list[MovementTypeFilter] | None, Query()] = None,  # 이 유형들만 (정정 CORRECTION 포함). 여러 개는 movement_type=SALE&movement_type=DISPOSAL, 잘못된 값은 422
    date_from: Annotated[date | None, Query()] = None,  # 이 날짜부터 (포함)
    date_to: Annotated[date | None, Query()] = None,  # 이 날짜까지 (포함)
    sort: Annotated[Literal["date", "registered"], Query()] = "date",  # date: 입출고일 최신순(기본), registered: 등록 순서 최신순
    include_current_stock: bool = False,  # 이력에 나온 품목의 현재고를 함께 조회한다.
) -> dict:
    if date_from and date_to and date_from > date_to:  # 거꾸로 된 기간은 빈 결과 대신 422 로 알려준다
        raise AppError(422, "VALIDATION_ERROR", "시작일은 종료일보다 늦을 수 없습니다.", [{"field": "date_from", "reason": "invalid"}])
    rows, meta = stock_service.list_movements(user.company_id, db, page, product_id, movement_type, date_from, date_to, sort)
    products = {p.id: p for p in products_service.products_by_ids(user.company_id, db, {m.product_id for m in rows})}  # 품목명·SKU 를 한 번에
    item_ids = {m.purchase_order_item_id for m in rows if m.purchase_order_item_id is not None}
    order_ids = dict(db.execute(select(PurchaseOrderItem.id, PurchaseOrderItem.purchase_order_id).where(
        PurchaseOrderItem.company_id == user.company_id, PurchaseOrderItem.id.in_(item_ids),
    )).all()) if item_ids else {}  # 같은 회사의 발주서만 연결한다.
    stocks = {s["product_id"]: s["current_stock"] for s in stock_service.stock_rows(
        user.company_id, db, list(products.values()),
    )} if include_current_stock and products else {}
    original_ids = {m.id for m in rows if m.movement_type != "CORRECTION"}
    corrected = dict(db.execute(select(
        InventoryMovement.reverses_movement_id, func.sum(InventoryMovement.quantity),
    ).where(
        InventoryMovement.company_id == user.company_id, InventoryMovement.reverses_movement_id.in_(original_ids),
    ).group_by(InventoryMovement.reverses_movement_id)).all()) if original_ids else {}
    data = []
    for m in rows:
        out = MovementOut.model_validate(m)  # 이력 칸
        product = products[m.product_id]
        out.product_sku, out.product_name, out.product_unit = product.sku, product.name, product.unit
        out.product_color, out.product_size, out.product_spec, out.product_group_code = product.color, product.size, product.spec, product.group_code
        out.purchase_order_id = order_ids.get(m.purchase_order_item_id)
        out.current_stock = stocks.get(m.product_id)
        if m.id in original_ids:
            out.correctable_quantity = m.quantity - corrected.get(m.id, 0)  # 품목 SKU·이름 덧붙이기
        data.append(out.model_dump(mode="json"))
    return {"data": data, "meta": meta}  # 정정 행은 reverses_movement_id 포함


@router.post("", status_code=201)  # 직접 입고·출고·조정 등록
def create_movement(data: MovementCreate, user: CurrentUser, db: DB) -> dict:
    movement, stock_after = stock_service.create_movement(user.company_id, db, user.id, data)  # 재고 부족이면 409
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 이력
    return {"data": {**body, "stock_after": stock_after}}  # 등록 직후 재고도 함께 (화면이 바로 숫자를 바꾸게)


@router.post("/{movement_id}/corrections", status_code=201)  # 잘못 넣은 이력 정정 (원래 이력은 고치지 않는다)
def create_correction(movement_id: PathId, data: CorrectionCreate, user: CurrentUser, db: DB) -> dict:
    movement, stock_after = stock_service.create_correction(user.company_id, db, user.id, movement_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 정정 이력
    return {"data": {**body, "stock_after": stock_after}}  # 응답 모양은 출고 등록과 같다
