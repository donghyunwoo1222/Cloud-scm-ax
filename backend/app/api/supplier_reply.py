"""공급업체 확인 링크 공개 경로 (#265 PR2). 로그인 의존성이 없다: 메일 링크 토큰(요청 본문)이 인증이다.

토큰은 주소가 아니라 POST 본문으로 받는다(서버 접근 로그·Referer 에 남지 않게). GET 으로 상태를 바꾸지 않는다.
"""

from fastapi import APIRouter, Response  # 라우터, 응답 머리글

from app.db import DB  # 요청마다 DB 세션
from app.schemas.supplier_reply import (  # 요청 모양 (extra 금지)
    SupplierReplyConfirm,
    SupplierReplyView,
)
from app.services import supplier_reply  # 업무 규칙

router = APIRouter(prefix="/supplier-reply")  # 이 파일의 경로는 모두 /supplier-reply 로 시작


@router.post("/view")  # 보기: 아무것도 바꾸지 않는다
def view(data: SupplierReplyView, db: DB, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"  # 브라우저·프록시가 발주 내용을 저장하지 않게
    return {"data": supplier_reply.view(db, data.token)}  # 404


@router.post("/confirm")  # 확인 버튼 (+ 회신 납기)
def confirm(data: SupplierReplyConfirm, db: DB, response: Response) -> dict:
    out = supplier_reply.confirm(db, data.token, data.due_date)  # 404·409·422
    db.commit()  # 확정 (발주서 잠금도 여기서 풀린다)
    response.headers["Cache-Control"] = "no-store"
    return {"data": out}
