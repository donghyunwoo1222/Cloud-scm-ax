"""입출고 등록·정정 경로 (F4). 관리자·담당자 모두 사용. 이력 수정·삭제 경로는 없다(잘못 넣은 건 정정으로)."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.schemas.movements import CorrectionCreate, MovementCreate, MovementOut  # 요청·응답 모양
from app.services import stock as stock_service  # 재고 업무 규칙

router = APIRouter(prefix="/inventory-movements")  # 이 파일의 경로는 모두 /inventory-movements 로 시작


@router.post("", status_code=201)  # 직접 입고·출고·조정 등록
def create_movement(data: MovementCreate, user: CurrentUser, db: DB) -> dict:
    movement, stock_after = stock_service.create_movement(user.company_id, db, user.id, data)  # 재고 부족이면 409
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 이력
    return {"data": {**body, "stock_after": stock_after}}  # 등록 직후 재고도 함께 (화면이 바로 숫자를 바꾸게)


@router.post("/{movement_id}/corrections", status_code=201)  # 잘못 넣은 이력 정정 (원래 이력은 고치지 않는다)
def create_correction(movement_id: int, data: CorrectionCreate, user: CurrentUser, db: DB) -> dict:
    movement, stock_after = stock_service.create_correction(user.company_id, db, user.id, movement_id, data)  # 404·409·422
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 정정 이력
    return {"data": {**body, "stock_after": stock_after}}  # 응답 모양은 출고 등록과 같다
