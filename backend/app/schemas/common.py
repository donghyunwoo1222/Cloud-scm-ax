"""여러 요청 모양이 함께 쓰는 칸 타입과 PATCH 규칙."""

from typing import Annotated, ClassVar  # 타입에 검사를 덧붙이는 도구, 클래스 공통 값

from fastapi import Header, Path, Query  # 헤더·경로·쿼리 칸 검사
from pydantic import BaseModel, Field, StringConstraints, model_validator  # 모양 정의·검사 도구

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]  # 이름류: 앞뒤 공백 제거 후 1~100자
# 정수 칸 (strict: 3.5·3.0·"3"·true 는 422). DB integer 칸은 2,147,483,647 까지라, 넘는 값은 DB 에 가기 전에 422 로 막는다(#71)
DB_INT_MAX = 2_147_483_647  # PostgreSQL integer 최댓값
Id = Annotated[int, Field(strict=True, le=DB_INT_MAX)]  # 본문의 번호 칸 (없는 번호면 404, 범위 밖이면 422)
PathId = Annotated[int, Path(le=DB_INT_MAX)]  # 주소 경로의 번호 (예: /products/{product_id})
QueryId = Annotated[int | None, Query(le=DB_INT_MAX)]  # 목록 필터의 번호 (예: ?supplier_id=)
IdempotencyKeyHeader = Annotated[str | None, Header(alias="Idempotency-Key", min_length=1, max_length=100)]  # 멱등 키 (#190). 없으면 지금처럼, 비었거나 100자 넘으면 422
MAX_QUANTITY = 1_000_000  # 박스 환산 후에도 적용하는 재고 단위 수량 상한
Quantity = Annotated[int, Field(strict=True, ge=1, le=MAX_QUANTITY)]  # 입출고·정정·발주·입고 수량
SafetyStock = Annotated[int, Field(strict=True, ge=0, le=1_000_000)]  # 안전재고: 0~100만 개
Won = Annotated[int, Field(strict=True, ge=0, le=100_000_000)]  # 단가(원): 0~1억 원
LeadTimeDays = Annotated[int, Field(strict=True, ge=0, le=365)]  # 리드타임: 0~365일
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
