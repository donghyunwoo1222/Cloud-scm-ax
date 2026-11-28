from fastapi import FastAPI  # FastAPI 앱 클래스

from app.api import (  # 경로가 든 모듈들
    auth,
    chat,
    companies,
    dashboard,
    health,
    import_templates,
    movements,
    product_imports,
    products,
    purchase_orders,
    receipt_imports,
    recommendations,
    sales_analytics,
    sales_imports,
    slack_events,
    slack_link,
    stock,
    supplier_reply,
    suppliers,
    users,
)
from app.config import settings  # APP_ENV·API_DOCS_ENABLED
from app.errors import register_error_handlers  # 공통 오류 응답 처리기
from app.services.login_otp import warn_if_disabled  # 관리자 인증코드 비상 스위치 경고 (#179)


def docs_urls(cfg) -> dict:
    """production 이고 API_DOCS_ENABLED 가 아니면 API 문서 주소를 모두 닫는다 (development 는 그대로 열림)."""
    if cfg.app_env == "production" and not cfg.api_docs_enabled:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {}


app = FastAPI(title="Cloud SCM + AX", **docs_urls(settings))  # 앱 시작점, 제목은 /docs API 문서에 표시된다
register_error_handlers(app)  # 오류를 {"error": {...}} 모양으로 맞춘다
warn_if_disabled()  # 시작할 때 ADMIN_OTP_ENABLED=false 면 경고 로그
app.include_router(health.router, prefix="/api/v1")  # 기존 API 상태 확인
app.include_router(health.probe_router)  # 배포 상태 확인은 루트에 등록한다
app.include_router(auth.router, prefix="/api/v1")  # 가입·로그인·로그아웃·내 정보
app.include_router(companies.router, prefix="/api/v1")  # 회사 정보 조회·수정
app.include_router(users.router, prefix="/api/v1")  # 직원 계정 관리 (관리자 전용)
app.include_router(suppliers.router, prefix="/api/v1")  # 공급업체
app.include_router(products.router, prefix="/api/v1")  # 품목
app.include_router(movements.router, prefix="/api/v1")  # 입출고 등록
app.include_router(stock.router, prefix="/api/v1")  # 재고 조회
app.include_router(purchase_orders.router, prefix="/api/v1")  # 발주서 작성·수정·조회
app.include_router(dashboard.router, prefix="/api/v1")  # 대시보드 요약
app.include_router(recommendations.router, prefix="/api/v1")  # 발주 추천 조회
app.include_router(sales_analytics.router, prefix="/api/v1")  # 판매 분석 (#357, 수량 집계)
app.include_router(sales_imports.router, prefix="/api/v1")  # 판매 가져오기 (CSV·엑셀)
app.include_router(receipt_imports.router, prefix="/api/v1")  # 품목·입고 가져오기 (CSV·엑셀)
app.include_router(product_imports.router, prefix="/api/v1")  # 품목 마스터 가져오기 (신규·수정, #189)
app.include_router(import_templates.router, prefix="/api/v1")  # 가져오기 템플릿 내려받기 (#189)
app.include_router(slack_link.router, prefix="/api/v1")  # 슬랙 연결 코드 발급·해제 (#197)
app.include_router(slack_events.router, prefix="/api/v1")  # 슬랙 Events API 받는 문 (#197, 로그인 대신 서명 검증)
app.include_router(supplier_reply.router, prefix="/api/v1")  # 공급업체 확인 링크 (#265, 로그인 대신 메일 링크 토큰)
app.include_router(chat.router, prefix="/api/v1")  # 안내 챗봇 (#199, 기본 꺼짐)
