"""품목 마스터 가져오기 경로 (#189). 관리자·담당자 모두 사용 (품목 등록 권한과 같다).

판매·입고 가져오기와 같이 세 경로 모두 파일(multipart)을 매번 다시 받고, 서버는 파일을 저장하지 않는다.
"""

from typing import Annotated  # 폼 칸 타입

from fastapi import APIRouter, File, Form, UploadFile  # 라우터, 파일·폼 칸
from pydantic import ValidationError  # options JSON 검사 실패

from app.api.sales_imports import read_upload  # 5MB 까지만 메모리로 읽기
from app.auth.deps import CurrentUser  # 로그인 사용자
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.schemas.product_import import ProductImportOptions  # 열 지정·옵션
from app.services import import_mapping  # LLM 열 매핑 제안 (#193)
from app.services import product_import as service  # 가져오기 업무 규칙

router = APIRouter(prefix="/product-imports")


def parse_options(options: str) -> ProductImportOptions:
    """폼의 options(JSON 글자)를 검사한다. 잘못되면 422."""
    try:
        return ProductImportOptions.model_validate_json(options)
    except ValidationError as e:
        details = [{"field": ".".join(str(p) for p in err["loc"]), "reason": err["msg"]} for err in e.errors()]
        raise AppError(422, "VALIDATION_ERROR", "열 지정이 올바르지 않습니다.", details) from None


@router.post("/inspect")  # 1단계: 머리글·행 수·열 미리 선택 힌트 (읽기만)
def inspect(user: CurrentUser, file: Annotated[UploadFile, File()]) -> dict:
    return {"data": service.inspect_file(*read_upload(file))}


@router.post("/suggest")  # 1-1단계(#193): LLM 열 매핑 제안. 실패해도 200 + source "rules" (읽기만)
def suggest(user: CurrentUser, file: Annotated[UploadFile, File()]) -> dict:
    return {"data": import_mapping.suggest(user.company_id, "products", *read_upload(file))}  # 회사는 토큰에서만


@router.post("/preview")  # 2단계: 신규 N·수정 M·변경 없음·문제 행 (읽기만)
def preview(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]) -> dict:
    return {"data": service.preview(user.company_id, db, *read_upload(file), parse_options(options))}


@router.post("", status_code=201)  # 3단계: 신규 등록 + 수정을 한 트랜잭션으로
def commit(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]) -> dict:
    data = service.commit(user.company_id, db, *read_upload(file), parse_options(options))  # 409·422 면 아무것도 쓰지 않는다
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    return {"data": data}
