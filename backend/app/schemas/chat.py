"""안내 챗봇(#199) 요청 모양. 길이·개수 한도는 여기서 막는다(넘으면 422).

예) 질문 500자 + 이전 질문 10개 × 500자 ≈ 최대 6,000자라 LLM 입력 상한(LLM_MAX_INPUT_CHARS 20,000자)에 닿기 전에 여기서 막힌다.
이전 답변 글은 받지 않는다(모르는 칸이면 422). 브라우저가 조작한 "이전 답변"을 LLM 이 사실처럼 이어 가지 않게 한다.
"""

from typing import Annotated  # 타입에 검사 조건 붙이기

from pydantic import BaseModel, ConfigDict, Field, StringConstraints  # 모양 정의·검사 도구

Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]  # 앞뒤 공백 제거 후 1~500자
SourceId = Annotated[str, StringConstraints(max_length=40)]  # 안내서 항목 ID (예: G-PO-APPROVE). 실제 ID 인지는 서버가 다시 본다


class ChatTurn(BaseModel):
    """이전 대화 한 번: 질문과 그때 받은 근거 ID 만."""

    model_config = ConfigDict(extra="forbid")  # answer 같은 모르는 칸이 오면 422

    question: Question
    sources: list[SourceId] = Field(default_factory=list, max_length=5)


class ChatGuideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Question
    history: list[ChatTurn] = Field(default_factory=list, max_length=10)  # 최근 이전 질문 10개까지 (넘으면 화면이 새 대화 안내)
