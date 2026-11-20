from sqlalchemy import (  # 참·거짓 칸, 값 검사, 외래키, 인덱스, 글자 칸
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸

KINDS = ("ORDER", "REMINDER")  # 발주서 메일(첫 발송·다시 보내기), 납기 독촉(#269 예약 값)
RESULTS = ("SENT", "FAILED", "UNSAVED")  # 성공 / 메일 서버 실패 / 메일은 나갔는데 발주서 저장 실패
FAILURE_CODES = ("AUTH", "RECIPIENT_REFUSED", "TIMEOUT", "CONNECTION", "OTHER")  # 실패 종류 (원문은 저장하지 않는다)


def _in(column: str, values: tuple[str, ...]) -> str:
    """CHECK 문장: column IN ('A', 'B')."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class PoEmailLog(CompanyMixin, Base):
    """메일 발송 시도 이력(#182): 메일 서버에 보낸 시도 하나가 한 행. 추가만 하고 수정·삭제하지 않는다.

    결과가 나온 뒤 한 행만 쓴다(시도 행을 먼저 쓰고 고치지 않는다). 토큰·본문·제목·첨부·실패 원문은 저장하지 않는다.
    시각(created_at)은 행을 넣은 트랜잭션의 시작 시각이다(emailed_at 과 같은 기준). 옛 기록 백필 행은 그때의 emailed_at.
    """

    __tablename__ = "po_email_log"  # DB 표 이름
    __table_args__ = (
        Index("ix_po_email_log_order", "company_id", "purchase_order_id", "id"),  # 발주서 하나의 이력 최신순·독촉 횟수 세기
        CheckConstraint(_in("kind", KINDS), name="ck_po_email_log_kind"),
        CheckConstraint(_in("result", RESULTS), name="ck_po_email_log_result"),
        CheckConstraint(  # 실패 코드는 실패일 때만, 실패면 반드시
            f"(result = 'FAILED' AND {_in('failure_code', FAILURE_CODES)}) OR (result <> 'FAILED' AND failure_code IS NULL)",
            name="ck_po_email_log_failure_code",
        ),
    )

    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"))  # 어느 발주서
    kind: Mapped[str] = mapped_column(Text)  # 종류 (KINDS)
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # 보낸 직원 (새 발송은 항상 채움, 옛 백필 행만 비어 있을 수 있다)
    to_address: Mapped[str | None] = mapped_column(Text)  # 그때의 받는 주소 (새 발송은 항상 채움, 옛 백필 행만 비어 있을 수 있다)
    result: Mapped[str] = mapped_column(Text)  # 결과 (RESULTS)
    failure_code: Mapped[str | None] = mapped_column(Text)  # 실패 종류 (FAILED 일 때만)
    with_link: Mapped[bool | None] = mapped_column(Boolean)  # 공급업체 확인 링크를 넣었는지 (옛 백필 행은 모름 = 비움). 토큰은 저장하지 않는다
