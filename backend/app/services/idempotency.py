"""멱등 키(#190): 같은 Idempotency-Key 로 다시 온 요청은 새로 저장하지 않고 첫 응답을 그대로 돌려준다.

대상: 직접 입출고·정정·발주 입고 POST. 헤더가 없으면 지금처럼 처리한다.

한 트랜잭션 안의 순서 (잠금 순서: 키 → 회사 → 발주서 → 품목):
  ① 이 회사의 24시간 지난 키를 지운다. SKIP LOCKED 라서 다른 요청이 잡은 행은 건너뛰고 절대 기다리지 않는다.
  ② 키 행을 먼저 넣는다(INSERT … ON CONFLICT DO NOTHING). 같은 키의 첫 요청이 아직 처리 중이면 DB 가 그 요청이 끝날 때까지
     여기서 기다리게 한다. 첫 요청이 커밋됐으면 넣지 않고 저장된 응답을 읽어 돌려주고, 실패(롤백)했으면 내 행이 들어간다.
  ③ 원래 처리 → ④ 키 행에 응답을 채우고 커밋.
처리 중 오류(409 CONFIRM_REQUIRED 포함)가 나면 롤백해 키 행도 함께 사라진다. 그래서 응답 칸이 빈 행은 커밋되지 않는다.
키를 기다리는 요청은 아직 다른 잠금을 잡지 않았으므로 기존 잠금과 서로 기다리는 일(교착)이 생기지 않는다.
쓰기 세션은 READ COMMITTED 라서 ② 다음 문장(SELECT)이 방금 커밋된 첫 요청의 행을 본다.
"""

import hashlib  # 요청 본문 지문 (SHA-256)
import json  # 본문을 정해진 글자로
from collections.abc import Callable  # 처리 함수 타입

from fastapi.responses import JSONResponse  # 저장된 상태 코드 그대로 돌려주기
from pydantic import BaseModel  # 요청 본문 모양
from sqlalchemy import delete, select, text  # DELETE·SELECT 문, SQL 조각
from sqlalchemy.dialects.postgresql import insert  # ON CONFLICT 가 되는 INSERT
from sqlalchemy.orm import Session  # DB 세션

from app.errors import AppError  # 공통 오류
from app.models import IdempotencyKey  # 멱등 키 표

EXPIRES = text("now() - interval '24 hours'")  # 24시간 지나면 만료


def request_hash(data: BaseModel) -> str:
    """요청 본문 지문. confirm_warnings 는 뺀다: 409 경고 뒤 확인하고 다시 보낸 요청은 같은 요청이다."""
    body = data.model_dump(mode="json", exclude={"confirm_warnings"})  # 검사를 마친 값 (빈 칸과 null 이 같게)
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def run(db: Session, company_id: int, endpoint: str, key: str | None, data: BaseModel, work: Callable[[], dict],
        status_code: int = 201):
    """work() 로 처리하고 커밋한다. key 가 있으면 같은 회사·경로·키의 첫 응답을 기억하고, 다시 오면 그대로 돌려준다."""
    if key is None:  # 헤더가 없으면 지금처럼
        body = work()
        db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
        return body

    digest = request_hash(data)
    stale = select(IdempotencyKey.id).where(
        IdempotencyKey.company_id == company_id, IdempotencyKey.created_at < EXPIRES,
    ).with_for_update(skip_locked=True)  # ① 만료 행, 다른 요청이 잡은 행은 건너뛴다
    db.execute(delete(IdempotencyKey).where(IdempotencyKey.id.in_(stale.scalar_subquery())))
    row_id = db.scalar(insert(IdempotencyKey).values(
        company_id=company_id, endpoint=endpoint, idempotency_key=key, request_hash=digest,
    ).on_conflict_do_nothing(index_elements=["company_id", "endpoint", "idempotency_key"]).returning(IdempotencyKey.id))  # ② 처리 중인 같은 키가 있으면 끝날 때까지 기다린다
    if row_id is None:  # 이미 처리된 키
        saved = db.execute(select(IdempotencyKey.request_hash, IdempotencyKey.status_code, IdempotencyKey.response_body).where(
            IdempotencyKey.company_id == company_id, IdempotencyKey.endpoint == endpoint, IdempotencyKey.idempotency_key == key,
        )).one()  # 새 문장이라 방금 커밋된 첫 요청의 행이 보인다 (READ COMMITTED)
        db.rollback()  # 읽기만 했다 (지운 만료 행도 되돌려 다음 요청이 정리)
        if saved.request_hash != digest:
            raise AppError(422, "IDEMPOTENCY_KEY_REUSED", "같은 요청 키로 다른 내용을 보냈습니다. 새로 등록하려면 화면을 새로 고쳐 다시 시도해 주세요.",
                           [{"field": "Idempotency-Key", "reason": "reused"}])
        return JSONResponse(saved.response_body, status_code=saved.status_code)  # 첫 응답 그대로 (상태 코드 포함)

    try:
        body = work()  # ③
    except Exception:
        db.rollback()  # 키 행도 함께 취소: 고친 뒤 같은 키로 다시 보낼 수 있다
        raise
    db.execute(IdempotencyKey.__table__.update().where(IdempotencyKey.id == row_id).values(
        status_code=status_code, response_body=body))  # ④ 응답을 채운 뒤에만 커밋한다
    db.commit()
    return body
