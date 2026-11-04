"""입출고 등록 경로 (F4). 관리자·담당자 모두 사용. 이력 수정·삭제 경로는 없다(정정은 #30)."""

from fastapi import APIRouter  # 라우터

from app.auth.deps import CurrentUser  # 로그인 사용자 (#22)
from app.db import DB  # 요청마다 DB 세션
from app.schemas.movements import MovementCreate, MovementOut  # 요청·응답 모양
from app.services import stock as stock_service  # 재고 업무 규칙

router = APIRouter(prefix="/inventory-movements")  # 이 파일의 경로는 모두 /inventory-movements 로 시작


@router.post("", status_code=201)  # 직접 입고·출고·조정 등록
def create_movement(data: MovementCreate, user: CurrentUser, db: DB) -> dict:
    movement, stock_after = stock_service.create_movement(user.company_id, db, user.id, data)  # 재고 부족이면 409
    body = MovementOut.model_validate(movement).model_dump(mode="json")  # 등록된 이력
    return {"data": {**body, "stock_after": stock_after}}  # 등록 직후 재고도 함께 (화면이 바로 숫자를 바꾸게)
