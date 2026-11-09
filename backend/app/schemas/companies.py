"""회사 정보 요청·응답 모양 (#156). 회사는 요청에 담지 않고 토큰에서만 정한다."""

import re  # 사업자번호 형식 검사
from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import BaseModel, BeforeValidator, ConfigDict

from app.schemas.common import OptionalText, PatchModel


def _business_number(value):
    """123-45-67890 도 1234567890 도 받고 숫자 10자리로 저장한다. 비우면(빈 글자) None. 그 밖은 422."""
    if not isinstance(value, str):
        return value  # None 은 비우기, 글자가 아닌 값은 그대로 넘겨 타입 오류(422)
    if not value.strip():
        return None  # 빈 글자는 비우기
    text = value.strip()
    if not re.fullmatch(r"\d{3}-?\d{2}-?\d{5}", text):  # 하이픈은 3-2-5 자리 위치에만 허용
        raise ValueError("사업자등록번호는 숫자 10자리(예: 123-45-67890)로 입력하세요.")
    return text.replace("-", "")


BusinessNumber = Annotated[str | None, BeforeValidator(_business_number)]  # 선택 칸


class CompanyUpdate(PatchModel):
    """바꿀 칸만 보낸다. 보내지 않은 칸은 그대로, null 이나 빈 글자는 비운다. (회사명은 이번 범위 밖)"""

    business_number: BusinessNumber = None  # 사업자등록번호
    representative: OptionalText = None  # 대표자
    address: OptionalText = None  # 주소
    phone: OptionalText = None  # 대표 연락처


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # Company 객체에서 같은 이름의 칸을 읽는다

    id: int
    name: str  # 회사명
    business_number: str | None  # 숫자 10자리 (화면이 123-45-67890 모양으로 보여 줄 수 있다)
    representative: str | None
    address: str | None
    phone: str | None
