from fastapi import FastAPI  # FastAPI 앱 클래스

from app.api import (  # 경로가 든 모듈들
    auth,
    dashboard,
    health,
    movements,
    products,
    purchase_orders,
    recommendations,
    sales_imports,
    stock,
    suppliers,
    users,
)
from app.errors import register_error_handlers  # 공통 오류 응답 처리기

app = FastAPI(title="Cloud SCM + AX")  # 앱 시작점, 제목은 /docs API 문서에 표시된다
register_error_handlers(app)  # 오류를 {"error": {...}} 모양으로 맞춘다
app.include_router(health.router, prefix="/api/v1")  # 모든 경로 앞에 /api/v1을 붙여 등록한다
app.include_router(auth.router, prefix="/api/v1")  # 가입·로그인·로그아웃·내 정보
app.include_router(users.router, prefix="/api/v1")  # 직원 계정 관리 (관리자 전용)
app.include_router(suppliers.router, prefix="/api/v1")  # 공급업체
app.include_router(products.router, prefix="/api/v1")  # 품목
app.include_router(movements.router, prefix="/api/v1")  # 입출고 등록
app.include_router(stock.router, prefix="/api/v1")  # 재고 조회
app.include_router(purchase_orders.router, prefix="/api/v1")  # 발주서 작성·수정·조회
app.include_router(dashboard.router, prefix="/api/v1")  # 대시보드 요약
app.include_router(recommendations.router, prefix="/api/v1")  # 발주 추천 조회
app.include_router(sales_imports.router, prefix="/api/v1")  # 판매 가져오기 (CSV·엑셀)
