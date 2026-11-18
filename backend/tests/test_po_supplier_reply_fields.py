"""공급업체 회신 칸(#265 PR1) 테스트: 기본값, 지연 기준(회신 납기 우선), 내보내기 열, 응답 누출, 사용자 없는 변경 이력."""

import csv
import io
from datetime import date, timedelta

from app.models import PoChangeLog, PurchaseOrder
from app.services import export
from app.services.po_change_log import log_change
from tests.helpers import login_as
from tests.test_dashboard import add_po, add_product, get

PO = "/api/v1/purchase-orders"
TODAY = date(2026, 11, 18)  # 고정 오늘


def freeze_today(monkeypatch):
    monkeypatch.setattr("app.api.dashboard.seoul_today", lambda: TODAY)
    monkeypatch.setattr("app.services.purchase_orders.seoul_today", lambda: TODAY)


def order_of(session, line):
    return session.get(PurchaseOrder, line.purchase_order_id)


def test_defaults_and_no_secret_in_response(client, world, session):
    """회신 칸 기본값은 비어 있고(횟수 0), 응답(상세·목록)에는 토큰 해시·만료가 없다."""
    p = add_product(session, world, "a", "DEF")
    line = add_po(session, world, "a", "D1", "ORDERED", p, 1, due_date=TODAY)
    order = order_of(session, line)
    order.supplier_token_hash, order.supplier_token_expires_at = "x" * 64, TODAY
    session.commit()
    assert (order.supplier_due_date, order.supplier_confirmed_at, order.supplier_reply_count) == (None, None, 0)
    login_as(client)
    for body in (client.get(f"{PO}/{order.id}").json()["data"], client.get(PO).json()["data"][0]):
        assert body["supplier_due_date"] is None and body["supplier_confirmed_at"] is None and body["supplier_reply_count"] == 0
        assert not any("token" in k for k in body)


def test_dashboard_and_filter_use_reply_due_date(client, world, session, monkeypatch):
    """회신 납기가 있으면 그 날짜가 지연 기준. 약속이 지났어도 회신이 미래면 지연 아님, 회신 날짜가 지나면 지연."""
    freeze_today(monkeypatch)
    p = add_product(session, world, "a", "REPLY")
    day = lambda n: TODAY + timedelta(days=n)
    add_po(session, world, "a", "NOLATE", "ORDERED", p, 1, due_date=day(-3), supplier_due_date=day(2))  # 약속은 지났지만 회신이 미래 → 지연 아님
    add_po(session, world, "a", "LATE-REPLY", "ORDERED", p, 1, due_date=day(-5), supplier_due_date=day(-1))  # 회신 날짜도 지남 → 지연
    add_po(session, world, "a", "EARLY-REPLY", "ORDERED", p, 1, due_date=day(5), supplier_due_date=day(-1))  # 회신이 약속보다 이름 → 지연
    add_po(session, world, "a", "NOREPLY", "ORDERED", p, 1, due_date=day(-1))  # 회신 없음 → 약속 기준(기존과 같음)
    add_po(session, world, "a", "TODAY", "ORDERED", p, 1, due_date=day(-2), supplier_due_date=day(0))  # 회신이 오늘 → 오늘 도착(지연 아님)
    session.commit()
    dash = get(client)["purchase_orders"]
    assert (dash["overdue"], dash["due_today"]) == (3, 1)
    names = lambda period: {o["po_number"] for o in client.get(PO, params={"receipt_due": period}).json()["data"]}
    assert names("OVERDUE") == {"LATE-REPLY", "EARLY-REPLY", "NOREPLY"}
    assert names("TODAY") == {"TODAY"}
    assert names("NEXT_7_DAYS") == {"NOLATE"}  # 회신이 2일 뒤


def test_change_log_without_user(client, world, session):
    """changed_by 가 NULL 인 이력 행은 이름이 '공급업체(메일 링크)' 로 나온다."""
    p = add_product(session, world, "a", "LOG")
    order = order_of(session, add_po(session, world, "a", "L1", "ORDERED", p, 1, due_date=TODAY))
    log_change(session, order.company_id, order.id, None, [("supplier_due_date", None, "2026-11-22")])
    session.commit()
    row = session.query(PoChangeLog).filter_by(purchase_order_id=order.id).one()
    assert row.changed_by is None
    login_as(client)
    data = client.get(f"{PO}/{order.id}/change-log").json()["data"]
    assert data[0]["changed_by_name"] == "공급업체(메일 링크)" and data[0]["field"] == "supplier_due_date"


def test_export_has_reply_due_last_column(client, world, session):
    """내보내기 맨 끝 열이 '회신 납기'. 값이 없으면 빈칸."""
    assert export.ORDER_HEADERS[-1] == "회신 납기"
    p = add_product(session, world, "a", "EXP")
    add_po(session, world, "a", "E1", "ORDERED", p, 1, due_date=TODAY, supplier_due_date=date(2026, 11, 22))
    add_po(session, world, "a", "E2", "ORDERED", p, 1, due_date=TODAY)
    session.commit()
    login_as(client)
    r = client.get(f"{PO}/export", params={"format": "csv"})
    table = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
    by_no = {row[0]: row[-1] for row in table[1:]}
    assert table[0][-1] == "회신 납기" and by_no == {"E1": "2026-11-22", "E2": ""}
