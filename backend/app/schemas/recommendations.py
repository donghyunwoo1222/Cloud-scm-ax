"""추천으로 초안 만들기 요청 모양 (#40)."""

from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import BaseModel, ConfigDict, Field  # 모양 정의·검사 도구

from app.schemas.common import Id, Quantity  # 번호·수량 칸 (상한 #71)


class DraftItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 추천 수량·단가 등 서버가 정하는 칸은 보내면 422

    product_id: Id  # 초안에 넣을 품목
    quantity: Quantity  # 사용자가 고친 발주 수량 (1~100만). 추천 수량은 서버가 다시 계산한다


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    items: Annotated[list[DraftItemIn], Field(min_length=1, max_length=100)]  # 1~100개 (목록 최대 page_size 와 같음, 사용자 결정)
