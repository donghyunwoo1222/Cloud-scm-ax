"""입출고 등록·정정 경로 (F4). 관리자·담당자 모두 사용. 이력 수정·삭제 경로는 없다(잘못 넣은 건 정정으로)."""

from datetime import date  # 기간 칸
from typing import Annotated, Literal  # 타입에 부가 정보를 붙이는 도구, 정해진 값 중 하나

from fastapi import (  # 라우터, 쿼리 문자열 칸, 요청 경로(멱등 키), 파일 응답
    APIRouter,
    Query,
    Request,
    Response,
)

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB, ReadDB  # 요청마다 DB 세션, 한 시점으로 읽는 조회 세션
from app.pagination import Page  # page·page_size
from app.schemas.common import (  # 멱등 키 헤더, 번호 칸 (DB 범위를 넘으면 422, #71)
    IdempotencyKeyHeader,
    PathId,
    QueryId,
)
from app.schemas.movements import (  # 요청·응답 모양
    CorrectionCreate,
    MovementCreate,
    MovementOut,
    MovementTypeFilter,
)
from app.services import (  # 목록 내보내기 (#191), 같은 요청 키는 한 번만 처리 (#190)
    export,
    idempotency,
)
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
    stock_service.check_period(date_from, date_to)  # 거꾸로 된 기간은 422
    rows, meta = stock_service.list_movements(user.company_id, db, page, product_id, movement_type, date_from, date_to, sort)
    data = stock_service.enrich_movements(user.company_id, db, rows, include_current_stock)  # 품목·발주서·정정 가능 수량 덧붙이기
    return {"data": data, "meta": meta}  # 정정 행은 reverses_movement_id 포함


@router.get("/export")  # 내보내기 (#191)
def export_movements(
    user: CurrentUser,  # 관리자·담당자 둘 다
    db: ReadDB,  # 여러 쪽을 나눠 읽는 동안 한 시점으로 읽는다
    fmt: Annotated[Literal["csv", "xlsx"], Query(alias="format")],  # 파일 형식 (그 밖은 422)
    product_id: QueryId = None,  # 아래 다섯 칸은 목록 경로와 같은 이름·검사 (쪽·현재고 칸은 없다)
    movement_type: Annotated[list[MovementTypeFilter] | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    sort: Annotated[Literal["date", "registered"], Query()] = "date",
) -> Response:
    return export.movements(user, db, fmt, product_id, movement_type, date_from, date_to, sort)  # 거꾸로 된 기간은 422


@router.post("", status_code=201)  # 직접 입고·출고·조정 등록
def create_movement(data: MovementCreate, user: CurrentUser, db: DB, request: Request, key: IdempotencyKeyHeader = None):
    def work() -> dict:
        movement, stock_after = stock_service.create_movement(user.company_id, db, user.id, data)  # 재고 부족 409, 확인 필요 409
        body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 이력
        return {"data": {**body, "stock_after": stock_after}}  # 등록 직후 재고도 함께 (화면이 바로 숫자를 바꾸게)
    return idempotency.run(db, user.company_id, request.url.path, key, data, work)  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)


@router.post("/{movement_id}/corrections", status_code=201)  # 잘못 넣은 이력 정정 (원래 이력은 고치지 않는다)
def create_correction(movement_id: PathId, data: CorrectionCreate, user: CurrentUser, db: DB, request: Request,
                      key: IdempotencyKeyHeader = None):
    def work() -> dict:
        movement, stock_after = stock_service.create_correction(user.company_id, db, user.id, movement_id, data)  # 404·409·422
        body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 정정 이력
        return {"data": {**body, "stock_after": stock_after}}  # 응답 모양은 출고 등록과 같다
    return idempotency.run(db, user.company_id, request.url.path, key, data, work)  # 요청 끝에 한 번만 확정
