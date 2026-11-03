# 표 정의 층: ERD의 7개 표. 여기서 모두 불러와야 Alembic이 Base.metadata 에서 7개를 다 본다
from app.models.base import Base  # 모든 모델의 부모
from app.models.company import Company  # 회사
from app.models.inventory_movement import InventoryMovement  # 입출고 이력
from app.models.product import Product  # 품목
from app.models.purchase_order import PurchaseOrder, PurchaseOrderItem  # 발주서, 발주 품목
from app.models.supplier import Supplier  # 공급업체
from app.models.user import User  # 사용자

__all__ = [  # 밖에서 from app.models import ... 로 쓸 이름 목록
    "Base",
    "Company",
    "InventoryMovement",
    "Product",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Supplier",
    "User",
]
