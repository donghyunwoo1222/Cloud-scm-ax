from datetime import date  # 날짜 칸의 파이썬 타입

from sqlalchemy import (  # 큰 정수, 값 검사, 날짜, 정수, 겹침 금지
    BigInteger,
    CheckConstraint,
    Date,
    Integer,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column  # 칸 정의 도구

from app.models.base import Base, CompanyMixin  # 공통 부모와 회사 칸

# 숫자 칸 이름. 질문·답변 글을 담는 칸은 두지 않는다(#199). 서비스가 이 목록 밖의 칸 이름을 쓰지 못하게 검사한다
COUNTERS = ("requests", "answered", "not_found", "data_question", "failed", "blocked_pii", "limited", "tokens_in")
# 피드백 칸(#199 PR4). COUNTERS 와 따로 둔다: add() 로는 올릴 수 없고 record_feedback() 의 상한 문장으로만 올린다
FEEDBACK = ("helpful", "not_helpful")


class ChatDailyStat(CompanyMixin, Base):
    """안내 챗봇 일별 통계(#199): 회사 하나 × 서울 날짜 하루 = 한 행. 숫자만 저장하는 기술용 기록이다.

    requests 는 LLM 으로 보낸 요청 수이고 챗봇 일일 상한을 이 숫자로 센다.
    요청이 끝나면 requests = answered + not_found + data_question + failed 가 된다(처리 중인 요청만큼은 잠깐 어긋난다).
    blocked_pii·limited 는 LLM 으로 보내지 않고 막은 수라 requests 에 넣지 않는다.
    피드백(helpful·not_helpful)은 requests 를 늘리지 않고, 합계가 그날 answered 를 넘지 못한다(DB 제약으로도 막는다).
    """

    __tablename__ = "chat_daily_stats"  # DB 표 이름
    __table_args__ = (
        UniqueConstraint("company_id", "day", name="uq_chat_daily_stats_company_day"),  # 회사·날짜당 한 행 (UPSERT 기준)
        *(CheckConstraint(f"{name} >= 0", name=f"ck_chat_daily_stats_{name}") for name in (*COUNTERS, *FEEDBACK)),
        CheckConstraint("helpful + not_helpful <= answered", name="ck_chat_daily_stats_feedback_le_answered"),
    )

    day: Mapped[date] = mapped_column(Date)  # 서울 기준 날짜
    requests: Mapped[int] = mapped_column(Integer, server_default="0")  # LLM 으로 보낸 요청 수 (일일 상한 기준)
    answered: Mapped[int] = mapped_column(Integer, server_default="0")  # 안내서 근거가 있는 답
    not_found: Mapped[int] = mapped_column(Integer, server_default="0")  # "찾지 못했습니다"
    data_question: Mapped[int] = mapped_column(Integer, server_default="0")  # 회사 데이터 질문이라 화면으로 안내
    failed: Mapped[int] = mapped_column(Integer, server_default="0")  # LLM 실패(503)
    blocked_pii: Mapped[int] = mapped_column(Integer, server_default="0")  # 개인정보 모양이라 보내지 않음
    limited: Mapped[int] = mapped_column(Integer, server_default="0")  # 분당 한도·일일 상한으로 막음
    tokens_in: Mapped[int] = mapped_column(BigInteger, server_default="0")  # 입력 토큰 합계 (호출당 평균 = tokens_in ÷ requests)
    helpful: Mapped[int] = mapped_column(Integer, server_default="0")  # "도움이 됐어요" 수 (ANSWER 답에만 버튼)
    not_helpful: Mapped[int] = mapped_column(Integer, server_default="0")  # "아니에요" 수
