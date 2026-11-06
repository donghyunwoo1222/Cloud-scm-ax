"""추천으로 초안 만들기 요청 모양 (#40)."""

from typing import Annotated  # 타입에 검사를 덧붙이는 도구

from pydantic import BaseModel, ConfigDict, Field, model_validator  # 모양 정의·검사 도구

from app.schemas.common import Id, Quantity  # 번호·수량 칸 (상한 #71)


class DraftItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 추천 수량·단가 등 서버가 정하는 칸은 보내면 422

    product_id: Id  # 초안에 넣을 품목
    quantity: Quantity | None = None  # 기존 방식으로 지정한 재고 단위 수량
    box_quantity: Quantity | None = None  # 지정한 박스 수. 둘 다 생략하면 박스 기본값을 적용한다

    @model_validator(mode="after")
    def at_most_one_quantity(self):
        if self.quantity is not None and self.box_quantity is not None:
            raise ValueError("quantity와 box_quantity를 함께 보낼 수 없습니다.")
        return self


class DraftCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 모르는 칸은 422

    items: Annotated[list[DraftItemIn], Field(min_length=1, max_length=100)]  # 1~100개 (목록 최대 page_size 와 같음, 사용자 결정)
