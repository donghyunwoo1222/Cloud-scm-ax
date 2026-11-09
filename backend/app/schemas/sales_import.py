"""판매 가져오기 요청 모양 (#154). 파일은 multipart 로, 아래 설정은 JSON 글자 한 칸(options)으로 함께 받는다."""

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구

from app.schemas.movements import SalesChannel  # 판매 채널 값


class SalesImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    product_col: int = Field(ge=0, le=1000)  # 상품 코드(SKU) 열 번호 (0부터)
    quantity_col: int = Field(ge=0, le=1000)  # 수량 열
    date_col: int = Field(ge=0, le=1000)  # 날짜 열 (이 값이 그대로 입출고일)
    ref_col: int = Field(ge=0, le=1000)  # 고유 주문번호 열 (중복 반영 방지에 쓴다)
    status_col: int | None = Field(default=None, ge=0, le=1000)  # (선택) 상태 열: 거르는 용도로만 읽고 저장하지 않는다
    statuses: list[str] | None = Field(default=None, max_length=50)  # 반영할 상태 값들 (상태 열이 있을 때)
    option_col: int | None = Field(default=None, ge=0, le=1000)  # (선택) 옵션 열: 섞임 경고용, 반영에는 안 쓴다
    sales_channel: SalesChannel | None = None  # 판매 채널 (반영 때 필수)
    exclude_problems: bool = False  # 문제 행을 빼고 반영할지
