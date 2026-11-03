"""오류 응답을 한 모양으로 맞춘다: {"error": {"code", "message", "details"}} (api-design.md)."""

from fastapi import FastAPI, Request  # 앱, 요청 객체
from fastapi.exceptions import RequestValidationError  # 요청 형태가 틀렸을 때 FastAPI가 내는 오류
from fastapi.responses import JSONResponse  # JSON 응답
from starlette.exceptions import HTTPException  # 없는 경로·깨진 본문 등 프레임워크 오류


class AppError(Exception):
    """업무 오류. 어디서든 raise 하면 아래 처리기가 정해진 모양의 응답으로 바꾼다."""

    def __init__(self, status: int, code: str, message: str, details=None):
        self.status = status  # HTTP 상태 코드 (예: 401, 409)
        self.code = code  # 프론트가 분기할 영문 코드 (예: EMAIL_TAKEN)
        self.message = message  # 화면에 그대로 보여줄 한국어 문장
        self.details = details  # 어느 칸이 문제인지 등 추가 정보 (없으면 None)


def error_body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}  # 공통 오류 모양


def register_error_handlers(app: FastAPI) -> None:
    """앱에 오류 처리기 두 개를 등록한다."""

    @app.exception_handler(AppError)  # 우리가 낸 업무 오류
    async def handle_app_error(request: Request, exc: AppError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)  # 그대로 옮긴다

    @app.exception_handler(HTTPException)  # 없는 경로(404), 깨진 본문(400) 등도 같은 모양으로
    async def handle_http_error(request: Request, exc: HTTPException):
        code = {404: "NOT_FOUND"}.get(exc.status_code, "HTTP_ERROR")  # 404만 api-design.md 의 코드로, 나머지는 공통 코드
        return JSONResponse(error_body(code, "요청을 처리할 수 없습니다.", exc.detail), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)  # 필수 칸 빠짐, 타입 틀림 등
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        details = [  # 칸마다 무엇이 문제인지
            {"field": ".".join(str(p) for p in err["loc"][1:]), "reason": err["msg"]}  # loc 맨 앞 "body"는 빼고 칸 이름만
            for err in exc.errors()
        ]
        return JSONResponse(error_body("VALIDATION_ERROR", "입력값을 확인해 주세요.", details), status_code=422)
