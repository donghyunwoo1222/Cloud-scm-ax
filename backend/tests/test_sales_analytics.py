"""판매 분석 API (#357) 테스트: GET /sales-analytics. 이력은 표에 직접 넣는다(조회만 시험)."""

from datetime import date, timedelta  # 고정 날짜(주 단위 시험), 날짜 이동

from app.clock import seoul_today  # 서울 기준 오늘
from app.services.sales_analytics import abc_grades, trend_buckets  # 순수 함수
from tests.helpers import login_as  # 공통 로그인
from tests.test_dashboard import (  # 품목·이력·발주 한 줄 만들기 (같은 모양 재사용)
    add_move,
    add_po,
    add_product,
)

URL = "/api/v1/sales-analytics"
TODAY = seoul_today()


def get(client, **params):
    login_as(client)  # A 담당자
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def by_sku(data):
    return {i["product_sku"]: i for i in data["items"]}


def test_requires_login(client, world):
    assert client.get(URL).status_code == 401


def test_bad_params(client, world):
    """기간은 7/30/90, 단위는 day/week 만."""
    login_as(client)
    assert client.get(URL, params={"days": 14}).status_code == 422
    assert client.get(URL, params={"bucket": "month"}).status_code == 422


def test_empty_company(client, world):
    """데이터 없음: 오류 없이 0, 추이는 0 으로 채움, 품목 없음."""
    d = get(client)
    assert d["total_quantity"] == 0 and d["items"] == []
    assert d["period"] == {"start": (TODAY - timedelta(days=29)).isoformat(), "end": TODAY.isoformat(), "days": 30, "bucket": "day"}
    assert len(d["trend"]) == 30 and all(t["quantity"] == 0 for t in d["trend"])
    assert d["source"] == "SALE_MOVEMENTS" and "판매 가져오기" in d["source_note"]


def test_net_sales_correction_and_excluded_types(client, world, session):
    """SALE 100 + 정정 30 → 70. 폐기·기타 출고·조정은 판매가 아니다. 품목별 합계가 이력 합계와 같다."""
    p = add_product(session, world, "a", "P1")
    add_move(session, world, "a", p, "RECEIPT", "IN", 500, 40)
    sale = add_move(session, world, "a", p, "SALE", "OUT", 100, 5)
    add_move(session, world, "a", p, "CORRECTION", "IN", 30, 2, reverses=sale.id)  # 정정은 원래 판매 날짜(5일 전)에서 빠진다
    add_move(session, world, "a", p, "DISPOSAL", "OUT", 7, 3)
    add_move(session, world, "a", p, "OTHER_OUT", "OUT", 9, 3)
    add_move(session, world, "a", p, "ADJUSTMENT", "OUT", 11, 3)
    d = get(client)
    item = by_sku(d)["P1"]
    assert item["quantity"] == 70 and item["sales_30d"] == 70 and d["total_quantity"] == 70
    assert item["current_stock"] == 500 - 100 + 30 - 7 - 9 - 11  # 403
    days = {t["start"]: t["quantity"] for t in d["trend"]}
    assert days[(TODAY - timedelta(days=5)).isoformat()] == 70 and days[(TODAY - timedelta(days=2)).isoformat()] == 0
    assert sum(days.values()) == 70  # 추이 합계 = 품목 합계


def test_cover_matches_recommendation(client, world, session):
    """소진 예상일의 일평균이 발주 추천 화면과 같다. 30일 판매 300, 현재고 50 → 일평균 10, 5.0일."""
    p = add_product(session, world, "a", "P1", safety_stock=20)
    add_move(session, world, "a", p, "RECEIPT", "IN", 350, 40)
    add_move(session, world, "a", p, "SALE", "OUT", 300, 10)
    item = by_sku(get(client))["P1"]
    assert item["cover_status"] == "OK" and item["avg_daily_sales"] == 10.0 and item["days_of_cover"] == 5.0
    rec = client.get("/api/v1/recommendations").json()["data"]
    assert [r["avg_daily_sales"] for r in rec["items"] if r["product_id"] == p.id] == [item["avg_daily_sales"]]


def test_no_sales_and_insufficient_data(client, world, session):
    """판매 없음·데이터 부족은 숨기지 않고 상태로, 숫자는 null. 순서는 추천과 같다(데이터 부족 먼저, S14)."""
    old = add_product(session, world, "a", "OLD")
    add_move(session, world, "a", old, "RECEIPT", "IN", 10, 40)  # 40일 전 입고, 판매 없음
    new = add_product(session, world, "a", "NEW")
    add_move(session, world, "a", new, "RECEIPT", "IN", 10, 10)  # 10일 전 첫 기록 + 판매 0 → 데이터 부족
    add_product(session, world, "a", "NONE")  # 이력 없음
    items = by_sku(get(client))
    assert items["OLD"]["cover_status"] == "NO_SALES_30D"
    assert items["NEW"]["cover_status"] == "INSUFFICIENT_DATA" and items["NONE"]["cover_status"] == "INSUFFICIENT_DATA"
    assert all(i["days_of_cover"] is None and i["avg_daily_sales"] is None and i["abc_grade"] is None for i in items.values())
    rec = {e["product_sku"]: e["code"] for e in client.get("/api/v1/recommendations").json()["data"]["excluded"]}
    assert rec["OLD"] == "NO_SALES_30D" and rec["NEW"] == "INSUFFICIENT_DATA"


def test_period_boundary(client, world, session):
    """7일 기간: 오늘−6일 포함, 오늘−7일 제외. 30일 일평균은 기간과 무관하게 같다."""
    p = add_product(session, world, "a", "P1")
    add_move(session, world, "a", p, "RECEIPT", "IN", 100, 40)
    add_move(session, world, "a", p, "SALE", "OUT", 3, 6)
    add_move(session, world, "a", p, "SALE", "OUT", 5, 7)
    d = get(client, days=7)
    assert d["period"]["start"] == (TODAY - timedelta(days=6)).isoformat() and len(d["trend"]) == 7
    item = by_sku(d)["P1"]
    assert item["quantity"] == 3 and item["sales_30d"] == 8


def test_other_company_hidden(client, world, session):
    """B 회사 품목·판매는 A 응답에 없다."""
    a = add_product(session, world, "a", "A1")
    add_move(session, world, "a", a, "RECEIPT", "IN", 50, 40)
    add_move(session, world, "a", a, "SALE", "OUT", 5, 1)
    b = add_product(session, world, "b", "B1")
    add_move(session, world, "b", b, "RECEIPT", "IN", 500, 40)
    add_move(session, world, "b", b, "SALE", "OUT", 400, 1)
    d = get(client)
    assert list(by_sku(d)) == ["A1"] and d["total_quantity"] == 5


def test_order_abc_and_inactive(client, world, session):
    """판매량 순서와 ABC (합 101: 앞 누적 0·50·80·95·100). 판매 없는 비활성 품목은 빠지고, 판매 있는 비활성 품목은 남는다."""
    for sku, qty in (("C", 5), ("A", 50), ("B2", 15), ("B", 30)):
        p = add_product(session, world, "a", sku)
        add_move(session, world, "a", p, "RECEIPT", "IN", 100, 40)
        add_move(session, world, "a", p, "SALE", "OUT", qty, 1)
    add_product(session, world, "a", "GONE", is_active=False)
    sold_inactive = add_product(session, world, "a", "OFF", is_active=False)
    add_move(session, world, "a", sold_inactive, "RECEIPT", "IN", 1, 40)
    add_move(session, world, "a", sold_inactive, "SALE", "OUT", 1, 1)
    items = get(client)["items"]
    assert [(i["product_sku"], i["abc_grade"]) for i in items] == [("A", "A"), ("B", "A"), ("B2", "A"), ("C", "B"), ("OFF", "C")]


def test_abc_grades_pure():
    assert abc_grades([50, 30, 15, 5]) == ["A", "A", "B", "C"]
    assert abc_grades([90, 10, 0]) == ["A", "B", None]  # 앞 누적 90% < 95% → B
    assert abc_grades([96, 4]) == ["A", "C"]
    assert abc_grades([]) == []


def test_week_buckets_cover_period():
    """주 단위: 월~일로 자르고 양 끝 주는 기간 안쪽만. 모든 날이 한 번씩만 들어간다."""
    start = TODAY - timedelta(days=89)
    daily = {start + timedelta(days=i): 1 for i in range(90)}
    rows = trend_buckets(daily, start, TODAY, "week")
    assert rows[0]["start"] == start.isoformat() and rows[-1]["end"] == TODAY.isoformat()
    assert sum(r["quantity"] for r in rows) == 90 and all(r["quantity"] <= 7 for r in rows)


# ── #357 후속: 소진 예상일을 발주 추천과 같은 기준(가용재고·리드타임)으로 ──


def rec_ids(client):
    """발주 추천 목록의 (추천 품목 id 집합, 제외 품목 id → 코드)."""
    rec = client.get("/api/v1/recommendations").json()["data"]
    return {r["product_id"] for r in rec["items"]}, {e["product_id"]: e["code"] for e in rec["excluded"]}


def test_in_transit_counts_toward_cover(client, world, session):
    """이전 점검의 TRANSIT 사례: 현재고 10, 입고 예정 500, 일평균 10 → 가용 510, 51.0일, 곧 소진 아님. 추천에도 없다."""
    p = add_product(session, world, "a", "TRANSIT", safety_stock=20)
    add_move(session, world, "a", p, "RECEIPT", "IN", 310, 40)
    add_move(session, world, "a", p, "SALE", "OUT", 300, 10)
    line = add_po(session, world, "a", "PO-T1", "ORDERED", p, 600)
    add_move(session, world, "a", p, "RECEIPT", "IN", 100, 1, po_item=line.id)  # 600 중 100 입고 → 남은 500
    item = by_sku(get(client))["TRANSIT"]
    assert (item["current_stock"], item["in_transit"], item["available_stock"]) == (110, 500, 610)
    assert item["days_of_cover"] == 61.0 and item["lead_time_days"] == 5 and item["cover_alert"] == "OK"
    recommended, _ = rec_ids(client)
    assert p.id not in recommended


def test_short_matches_recommendation(client, world, session):
    """일평균 10, 리드타임 5, 안전재고 20 → 기준 70. 가용 50 → SHORT 이고 추천 대상. 가용 71 → OK 이고 추천 아님. 70 (같음) → SHORT."""
    cases = {"S50": 50, "S70": 70, "S71": 71}
    for sku, stock in cases.items():
        p = add_product(session, world, "a", sku, safety_stock=20)
        add_move(session, world, "a", p, "RECEIPT", "IN", 300 + stock, 40)
        add_move(session, world, "a", p, "SALE", "OUT", 300, 10)
    items = by_sku(get(client))
    assert {s: items[s]["cover_alert"] for s in cases} == {"S50": "SHORT", "S70": "SHORT", "S71": "OK"}
    recommended, _ = rec_ids(client)
    assert {i["product_id"] for i in items.values() if i["cover_alert"] == "SHORT"} == recommended


def test_unknown_lead_time_without_supplier(client, world, session):
    """기본 공급업체가 비활성이면 리드타임 null, cover_alert UNKNOWN. 소진 예상일 숫자는 남는다. 추천은 MISSING_INFO."""
    p = add_product(session, world, "a", "NOSUP")
    add_move(session, world, "a", p, "RECEIPT", "IN", 310, 40)
    add_move(session, world, "a", p, "SALE", "OUT", 300, 10)  # 가용 10, 일평균 10 → 1.0일 (리드타임이 있었다면 SHORT)
    world["a_supplier"].is_active = False
    session.flush()
    item = by_sku(get(client))["NOSUP"]
    assert item["lead_time_days"] is None and item["cover_alert"] == "UNKNOWN" and item["days_of_cover"] == 1.0
    _, excluded = rec_ids(client)
    assert excluded[p.id] == "MISSING_INFO"


def test_alert_consistency_sweep(client, world, session):
    """여러 모양의 품목을 한 번에: SHORT ⇔ 추천 대상, 추천에서 제외된 품목은 SHORT 가 아니다, 비활성 품목은 UNKNOWN."""
    shapes = [("LOW", 5, 0), ("HIGH", 900, 0), ("COMING", 5, 400), ("NEW", None, 0), ("QUIET", 10, 0)]
    for sku, stock, coming in shapes:
        p = add_product(session, world, "a", sku, safety_stock=3)
        if stock is None:
            add_move(session, world, "a", p, "RECEIPT", "IN", 50, 3)  # 첫 기록 3일 전 → 데이터 부족
            add_move(session, world, "a", p, "SALE", "OUT", 40, 1)
            continue
        add_move(session, world, "a", p, "RECEIPT", "IN", stock + (0 if sku == "QUIET" else 90), 40)
        if sku != "QUIET":
            add_move(session, world, "a", p, "SALE", "OUT", 90, 5)  # 일평균 3
        if coming:
            add_po(session, world, "a", f"PO-{sku}", "ORDERED", p, coming)
    off = add_product(session, world, "a", "OFF", is_active=False)
    add_move(session, world, "a", off, "RECEIPT", "IN", 91, 40)
    add_move(session, world, "a", off, "SALE", "OUT", 90, 1)
    items = by_sku(get(client))
    recommended, excluded = rec_ids(client)
    for sku, i in items.items():
        assert (i["cover_alert"] == "SHORT") == (i["product_id"] in recommended), sku
        if i["product_id"] in excluded:
            assert i["cover_alert"] == "UNKNOWN", sku
    assert items["LOW"]["cover_alert"] == "SHORT" and items["COMING"]["cover_alert"] == "OK" and items["HIGH"]["cover_alert"] == "OK"
    assert items["OFF"]["cover_alert"] == "UNKNOWN" and items["OFF"]["lead_time_days"] is None
    assert items["OFF"]["days_of_cover"] == 0.3  # 숫자는 보인다 (가용 1 ÷ 일평균 3)


def _weeks(start: date, end: date) -> list[tuple[str, int]]:
    return [(r["start"][5:], r["days"]) for r in trend_buckets({}, start, end, "week")]


def test_week_days_sunday_start_and_today_weekday():
    """2026-11-22 는 일요일, 11-28 은 토요일, 11-29 는 일요일, 11-30 은 월요일. 시계는 인자로 고정한다."""
    assert _weeks(date(2026, 11, 22), date(2026, 11, 28)) == [("11-22", 1), ("11-23", 6)]  # 첫날 일요일 → 하루짜리 주, 오늘 토요일 → 진행 중 6일
    assert _weeks(date(2026, 11, 23), date(2026, 11, 29)) == [("11-23", 7)]  # 오늘 일요일 → 꽉 찬 한 주
    assert _weeks(date(2026, 11, 24), date(2026, 11, 30)) == [("11-24", 6), ("11-30", 1)]  # 오늘 월요일 → 마지막 주 1일
    rows = trend_buckets({}, date(2026, 11, 1), date(2026, 11, 30), "day")
    assert all(r["days"] == 1 for r in rows) and len(rows) == 30
    week = trend_buckets({date(2026, 8, 31) + timedelta(days=i): 1 for i in range(90)}, date(2026, 8, 31), date(2026, 11, 28), "week")
    assert sum(r["days"] for r in week) == 90 and all(r["quantity"] == r["days"] for r in week)  # 모든 날이 한 번씩
