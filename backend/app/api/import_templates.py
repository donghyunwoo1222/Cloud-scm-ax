"""가져오기 템플릿 내려받기 (#189). 읽기만 하는 GET 이라 상태를 바꾸지 않는다."""

from fastapi import APIRouter, Response  # 라우터, 파일 응답

from app.auth.deps import CurrentUser  # 로그인 사용자
from app.errors import AppError  # 공통 오류
from app.services import import_templates as service  # 템플릿 만들기

router = APIRouter(prefix="/import-templates")

NAMES = {f"{kind}.{fmt}" for kind in ("products", "sales") for fmt in ("xlsx", "csv")}  # 허용하는 파일 이름 4개


@router.get("/{name}")  # 예) /import-templates/products.xlsx
def download(user: CurrentUser, name: str) -> Response:
    if name not in NAMES:
        raise AppError(404, "NOT_FOUND", "없는 템플릿입니다.")
    kind, fmt = name.split(".")
    content, media_type = service.build(kind, fmt)
    return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{kind}-template.{fmt}"'})
