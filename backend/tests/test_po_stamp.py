"""발주서 도장·승인 기록(#263): 승인 시점 회사명 저장, 문서 응답 approval, 도장 글자 규칙, 마이그레이션 백필."""

import importlib.util  # 마이그레이션 파일의 백필 SQL 을 그대로 불러온다
import re  # 시각 글자 형식 검사
from pathlib import Path  # 마이그레이션 파일 위치

import pytest  # 테스트 도구
from sqlalchemy import text  # 백필 SQL 실행

from app.models import PurchaseOrder  # 발주서 표
from app.services.export import seoul_time  # 서울 시각 글자 (기대값)
from app.services.po_document import stamp_of  # 도장 글자 규칙 (순수 함수)
from tests.helpers import login_as  # 공통 로그인
from tests.test_po_document import URL, make_order  # 문서 테스트의 준비 도구

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "c9e4a7b2d5f1_po_approved_company_name.py"


@pytest.mark.parametrize(("name", "lines", "ratio"), [
    ("가", ["가"], 0.36),  # 0.7/1 → 상한 0.36
    ("가나", ["가나"], 0.35),
    ("가나다", ["가나다"], 0.233),
    ("가나다라", ["가나", "다라"], 0.35),  # 4~6자는 2줄
    ("가나다라마", ["가나다", "라마"], 0.233),
    ("가나다라마바", ["가나다", "라마바"], 0.233),
    ("가나다라마바사", ["가나다", "라마", "바사"], 0.233),  # 7~9자는 3줄, 남는 글자는 앞줄부터
    ("가나다라마바사아", ["가나다", "라마바", "사아"], 0.233),
    ("가나다라마바사아자", ["가나다", "라마바", "사아자"], 0.233),
    ("가나다라마바사아자차", ["가나다", "라마바", "사아자"], 0.233),  # 10자 이상은 앞 9자
    ("가" * 20, ["가가가"] * 3, 0.233),
    ("(주)한빛", ["한빛"], 0.35),
    ("주식회사 한빛생활", ["한빛", "생활"], 0.35),
    ("㈜한빛", ["한빛"], 0.35),
    ("(주)", ["(주)"], 0.233),  # 떼고 나면 비므로 원래 이름
    ("   ", ["인"], 0.36),  # 공백뿐이면 "인"
    ("A&B<주>", ["A&B", "<주>"], 0.233),  # 이스케이프하지 않고 글자 그대로
    ("Hanbit Living", ["Han", "bit", "Liv"], 0.233),  # 공백을 지운 뒤 앞 9자
    (" 한 빛  생 활 ", ["한빛", "생활"], 0.35),  # 안쪽 공백도 지운다
])
def test_stamp_of(name, lines, ratio):
    assert stamp_of(name) == {"lines": lines, "ratio": ratio}


def test_approve_saves_company_name_and_document_keeps_it(client, session, world):
    order, _ = make_order(client, session, world)
    session.expire_all()  # 앱이 바꾼 값을 다시 읽는다
    saved = session.get(PurchaseOrder, order["id"])
    assert saved.approved_company_name == "회사A"

    world["a_company"].name = "새이름상사"  # 회사명 변경 API 는 없어서 직접 바꾼다
    session.commit()
    doc = client.get(f"{URL}/{order['id']}/document").json()["data"]
    assert doc["buyer"]["name"] == "새이름상사"  # 발주처 상호는 현재 이름
    assert doc["approval"] == {
        "approver_name": "a-ADMIN",
        "approved_at": seoul_time(saved.approved_at),
        "company_name": "회사A",  # 도장은 승인 때 이름 그대로
        "stamp": {"lines": ["회사A"], "ratio": 0.233},
    }
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", doc["approval"]["approved_at"])


def test_document_without_approval_fields_uses_current_name(client, session, world):
    order = PurchaseOrder(company_id=world["a_company"].id, supplier_id=world["a_supplier"].id, po_number="PO-X",
                          status="ORDERED", created_by=world["a_admin"].id)  # test_corrections 처럼 승인 칸 없이 직접 만든 발주서
    session.add(order)
    session.commit()
    login_as(client, "admin@a.test")
    response = client.get(f"{URL}/{order.id}/document")
    assert response.status_code == 200, response.json()
    assert response.json()["data"]["approval"] == {
        "approver_name": None, "approved_at": None, "company_name": "회사A",
        "stamp": {"lines": ["회사A"], "ratio": 0.233},
    }


def test_backfill_fills_only_approved_orders(client, session, world):
    approved, _ = make_order(client, session, world)
    draft = PurchaseOrder(company_id=world["a_company"].id, supplier_id=world["a_supplier"].id, po_number="PO-D",
                          created_by=world["a_admin"].id)  # DRAFT (승인 칸 없음)
    session.add(draft)
    session.commit()
    session.execute(text("UPDATE purchase_orders SET approved_company_name = NULL"))  # 마이그레이션 직전 상태로

    spec = importlib.util.spec_from_file_location("migration", MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)  # alembic op 는 upgrade() 를 부를 때만 쓰므로 불러오기만은 안전
    session.execute(text(migration.BACKFILL))
    session.expire_all()
    assert session.get(PurchaseOrder, approved["id"]).approved_company_name == "회사A"
    assert session.get(PurchaseOrder, draft.id).approved_company_name is None
