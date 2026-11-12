from sqlalchemy import Index, String  # 인덱스, 글자 칸
from sqlalchemy.dialects.postgresql import JSONB  # 응답 본문을 JSON 그대로 저장
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸


class IdempotencyKey(CompanyMixin, Base):
    """멱등 키(#190): 같은 요청을 두 번 보내도 한 번만 처리하려고 첫 응답을 24시간 기억한다. 업무 데이터가 아닌 기술용 기록.

    행은 키를 먼저 넣고(응답 칸 비움) 처리가 끝난 뒤 응답을 채워 함께 커밋한다. 처리가 실패하면 함께 취소돼 남지 않는다.
    """

    __tablename__ = "idempotency_keys"  # DB 표 이름
    __table_args__ = (
        Index("uq_idempotency_company_endpoint_key", "company_id", "endpoint", "idempotency_key", unique=True),  # 회사·경로마다 키 하나
    )

    idempotency_key: Mapped[str] = mapped_column(String(100))  # 화면이 보낸 Idempotency-Key 헤더 값
    endpoint: Mapped[str] = mapped_column(String(200))  # 요청 경로 (예: /api/v1/purchase-orders/12/receipts). 경로가 다르면 다른 키
    request_hash: Mapped[str] = mapped_column(String(64))  # 요청 본문 지문(SHA-256, confirm_warnings 제외). 같은 키에 다른 내용이면 422
    status_code: Mapped[int | None]  # 첫 응답의 상태 코드 (넣는 순간에는 비어 있고 커밋 전에 채운다)
    response_body: Mapped[dict | None] = mapped_column(JSONB)  # 첫 응답 본문
