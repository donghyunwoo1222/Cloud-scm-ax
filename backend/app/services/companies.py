"""회사 정보 (#156). 회사는 항상 토큰 사용자의 company_id 로만 정한다."""

from sqlalchemy.orm import Session

from app.models import Company
from app.schemas.companies import CompanyUpdate


def get_company(company_id: int, db: Session) -> Company:
    return db.get_one(Company, company_id)  # 토큰 사용자의 회사라 항상 있다


def update_company(company_id: int, db: Session, data: CompanyUpdate) -> Company:
    """보낸 칸만 바꾼다. 빈 글자는 비우기(None)로 저장한다."""
    company = get_company(company_id, db)
    for field, value in data.model_dump(exclude_unset=True).items():  # 요청에 들어 있던 칸만
        setattr(company, field, value or None)  # "" → None
    db.commit()  # 확정
    return company
