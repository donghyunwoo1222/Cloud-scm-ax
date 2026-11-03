"""여러 요청 모양이 함께 쓰는 칸 타입과 PATCH 규칙."""

from typing import Annotated, ClassVar  # 타입에 검사를 덧붙이는 도구, 클래스 공통 값

from pydantic import BaseModel, Field, StringConstraints, model_validator  # 모양 정의·검사 도구

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]  # 이름류: 앞뒤 공백 제거 후 1~100자
NonNegInt = Annotated[int, Field(ge=0, strict=True)]  # 0 이상 정수만 (strict: 3.5·3.0·"3"·true 는 422)
OptionalText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None  # 선택 칸: 200자까지, 비워도 됨
Memo = Annotated[str, StringConstraints(max_length=1000)] | None  # 메모: 1000자까지


class PatchModel(BaseModel):
    """PATCH 요청 공통: 보낸 칸만 바꾼다. 선택 칸에 null 이면 비우고, REQUIRED 칸에 null 이면 422."""

    REQUIRED: ClassVar[tuple[str, ...]] = ()  # 자식 클래스가 null 로 비울 수 없는 칸 이름을 적는다

    @model_validator(mode="after")
    def required_fields_not_null(self):
        for field in self.REQUIRED:  # 필수 칸마다
            if field in self.model_fields_set and getattr(self, field) is None:  # 보냈는데 null 이면
                raise ValueError(f"{field} 는 비울 수 없습니다.")  # → 422 VALIDATION_ERROR
        return self
