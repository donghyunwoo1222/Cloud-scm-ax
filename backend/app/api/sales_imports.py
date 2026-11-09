"""판매 가져오기 경로 (#154). 관리자·담당자 모두 사용 (손으로 출고를 등록하는 권한과 같다).

세 경로 모두 파일(multipart)을 매번 다시 받는다. 서버는 파일을 저장하지 않는다.
"""

from typing import Annotated  # 폼 칸 타입

from fastapi import APIRouter, File, Form, UploadFile  # 라우터, 파일·폼 칸
from pydantic import ValidationError  # options JSON 검사 실패

from app.auth.deps import CurrentUser  # 로그인 사용자
from app.db import DB  # 요청마다 DB 세션
from app.errors import AppError  # 공통 오류
from app.schemas.sales_import import SalesImportOptions  # 열 지정·옵션
from app.services import sales_import as service  # 가져오기 업무 규칙

router = APIRouter(prefix="/sales-imports")


def read_upload(file: UploadFile) -> tuple[str, bytes]:
    """파일을 메모리로 읽는다. 5MB 를 넘으면 더 읽지 않고 거절한다."""
    content = file.file.read(service.MAX_BYTES + 1)
    return file.filename or "", content


def parse_options(options: str) -> SalesImportOptions:
    """폼의 options(JSON 글자)를 검사한다. 잘못되면 422."""
    try:
        return SalesImportOptions.model_validate_json(options)
    except ValidationError as e:
        details = [{"field": ".".join(str(p) for p in err["loc"]), "reason": err["msg"]} for err in e.errors()]
        raise AppError(422, "VALIDATION_ERROR", "열 지정이 올바르지 않습니다.", details) from None


@router.post("/inspect")  # 1단계: 머리글·행 수·열 미리 선택 힌트 (읽기만)
def inspect(
    user: CurrentUser, file: Annotated[UploadFile, File()], status_col: Annotated[int | None, Form(ge=0, le=1000)] = None,
) -> dict:
    name, content = read_upload(file)
    return {"data": service.inspect_file(name, content, status_col)}


@router.post("/preview")  # 2단계: 반영 N건·건너뜀·문제 행 (읽기만, 아무것도 쓰지 않는다)
def preview(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]) -> dict:
    name, content = read_upload(file)
    return {"data": service.preview(user.company_id, db, name, content, parse_options(options))}


@router.post("", status_code=201)  # 3단계: SALE 이력을 한 트랜잭션으로 쌓는다
def commit(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()], options: Annotated[str, Form()]) -> dict:
    name, content = read_upload(file)
    data = service.commit(user.company_id, db, user.id, name, content, parse_options(options))  # 409 면 아무것도 쓰지 않는다
    db.commit()  # 요청 끝에 한 번만 확정 (잠금도 여기서 풀린다)
    return {"data": data}
