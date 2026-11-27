# 표 정의 층: ERD의 13개 표(업무 7개 + 멱등 키 + 발주서 변경 이력 + 슬랙 연결 + 메일 발송 이력 + 챗봇 일별 통계 + 가입 제한). 여기서 모두 불러와야 Alembic이 Base.metadata 에서 다 본다
from app.models.base import Base  # 모든 모델의 부모
from app.models.chat_daily_stat import ChatDailyStat  # 안내 챗봇 일별 통계 (#199)
from app.models.company import Company  # 회사
from app.models.idempotency_key import IdempotencyKey  # 멱등 키 (#190)
from app.models.inventory_movement import InventoryMovement  # 입출고 이력
from app.models.po_change_log import PoChangeLog  # 발주서 변경 이력 (#181)
from app.models.po_email_log import PoEmailLog  # 메일 발송 시도 이력 (#182)
from app.models.product import Product  # 품목
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem  # 발주서, 발주 품목
from app.models.signup_rate_limit import SignupRateLimit  # 가입 제한
from app.models.slack_link import SlackLink  # 슬랙 연결 (#197)
from app.models.supplier import Supplier  # 공급업체
from app.models.user import User  # 사용자

__all__ = [  # 밖에서 from app.models import ... 로 쓸 이름 목록
    "Base",
    "ChatDailyStat",
    "Company",
    "IdempotencyKey",
    "InventoryMovement",
    "PoChangeLog",
    "PoEmailLog",
    "Product",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "SignupRateLimit",
    "SlackLink",
    "Supplier",
    "User",
]
