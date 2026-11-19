"""공급업체 확인 링크 공개 API 요청 모양 (#265 PR2). 회사·발주 id 칸은 없고, 모르는 칸은 422 로 거절한다."""

from datetime import date  # 회신 납기

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구


class SupplierReplyView(BaseModel):
    """POST /supplier-reply/view: 메일 링크의 # 뒤 토큰만 받는다."""

    model_config = ConfigDict(extra="forbid")  # company_id·발주 id 같은 칸을 몰래 보내도 받지 않는다
    token: str = Field(min_length=1, max_length=100)  # 발급 토큰은 43자. 길이 오류 응답은 입력값을 되돌려 주지 않는다(errors.py)


class SupplierReplyConfirm(SupplierReplyView):
    """POST /supplier-reply/confirm: 확인 버튼. 납기를 함께 보내면 회신 납기로 기록한다."""

    due_date: date | None = None  # 비우면 확인만 (범위 검사는 서비스: 서울 기준 오늘 ~ 1년 뒤)
