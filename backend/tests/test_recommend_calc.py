"""추천 계산 순수 함수 (#38) 테스트. DB 없이 숫자만 넣는다. 오늘 날짜는 고정한다.

시나리오 번호는 docs/04-ax-design/ax-design.md "1단계: 정답 시나리오". 공통 조건: 일평균 10(30일 판매 300), 리드타임 5, 안전재고 20.
S8(회사 분리)은 추천 API(#39), S9·S10(초안)은 #40, S11(승인 권한)은 test_po_status.py 에서 확인한다.
"""

from datetime import date, timedelta  # 날짜, 날짜 빼기
from fractions import Fraction  # 정확한 분수 비교

from app.services.recommend import Excluded, Recommendation, calculate_recommendation  # 시험 대상

TODAY = date(2026, 11, 4)  # 고정한 오늘
BASE = {  # 공통 조건 (각 테스트가 필요한 칸만 바꾼다)
    "today": TODAY,
    "first_movement_date": TODAY - timedelta(days=60),  # 데이터 충분 (60일 전 첫 기록)
    "supplier_active": True,  # 기본 공급업체 활성
    "sales_30d": 300,  # 30일 판매 300 → 일평균 10
    "stock": 50,  # 현재고
    "in_transit": 0,  # 오는 중인 발주
    "lead_time": 5,  # 리드타임 5일
    "safety_stock": 20,  # 안전재고 20
}


def calc(**changes):
    """공통 조건에서 바꾼 칸만 넣어 계산한다."""
    return calculate_recommendation(**{**BASE, **changes})


# ----- 정답 시나리오 S1~S7, S12~S14 -----

def test_s1_shortage_recommends_160():
    """S1: 현재고 50, 진행 0 → 재주문점 70, 추천 160."""
    r = calc()
    assert r == Recommendation(
        avg_daily_sales=Fraction(10), available=50, reorder_point=Fraction(70), recommended_quantity=160,
        reason="최근 30일 하루 평균 10개가 팔렸고 리드타임은 5일입니다. 리드타임 동안 50개가 필요하고 "
               "안전재고 20개를 더하면 70개입니다. 지금 가용재고는 50개라서 발주를 추천합니다. 추천 수량은 160개입니다.",
    )


def test_s2_enough_stock_no_recommendation():
    """S2: 현재고 150 → 150 > 70 이라 추천 없음 (계산 숫자는 돌려준다)."""
    r = calc(stock=150)
    assert r == Recommendation(Fraction(10), 150, Fraction(70), None, None)


def test_s3_already_ordered_no_recommendation():
    """S3: 현재고 50 + ORDERED 160 → 가용재고 210 > 70 이라 추천 없음."""
    r = calc(in_transit=160)
    assert r.available == 210
    assert r.recommended_quantity is None


def test_s4_cancelled_order_counts_as_zero():
    """S4: CANCELLED 160 은 진행 중 수량에 넣지 않는다(#39 조회 몫) → 진행 0 으로 계산, 추천 160."""
    r = calc(in_transit=0)
    assert r.recommended_quantity == 160


def test_s5_no_sales_30d():
    """S5: 30일 판매 0 → NO_SALES_30D, "최근 30일 판매 없음"."""
    assert calc(sales_30d=0) == Excluded("NO_SALES_30D", "최근 30일 판매 없음")


def test_s6_insufficient_data_13_days():
    """S6: 첫 입출고 후 13일 → 데이터 부족."""
    assert calc(first_movement_date=TODAY - timedelta(days=13)) == Excluded("INSUFFICIENT_DATA", "데이터 부족")


def test_s7_inactive_supplier_missing_info():
    """S7: 기본 공급업체 비활성 → MISSING_INFO 와 안내 문장."""
    assert calc(supplier_active=False) == Excluded("MISSING_INFO", "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요")


def test_s12_decimal_ceil_to_7():
    """S12: 30일 판매 7, 리드타임 5, 안전재고 2, 가용재고 0 → 일평균 0.233…, 재주문점 3.17, 6.43 → 7."""
    r = calc(sales_30d=7, safety_stock=2, stock=0)
    assert r.avg_daily_sales == Fraction(7, 30)  # 소수 그대로 (반올림하지 않음)
    assert r.reorder_point == Fraction(19, 6)  # 3.1666…
    assert r.recommended_quantity == 7
    assert r.reason == (  # 문구의 소수는 첫째 자리까지
        "최근 30일 하루 평균 0.2개가 팔렸고 리드타임은 5일입니다. 리드타임 동안 1.2개가 필요하고 "
        "안전재고 2개를 더하면 3.2개입니다. 지금 가용재고는 0개라서 발주를 추천합니다. 추천 수량은 7개입니다."
    )


def test_s13_net_sales_after_correction():
    """S13: SALE 100 + 정정 90 → 순판매 10 이 들어오면 일평균 10/30 으로 계산한다(빼기 조회는 #39, DB 수준은 test_corrections.py)."""
    r = calc(sales_30d=100 - 90)
    assert r.avg_daily_sales == Fraction(1, 3)


def test_s14_insufficient_data_wins_over_no_sales():
    """S14: 첫 기록 10일 전 + 30일 판매 0 → INSUFFICIENT_DATA (NO_SALES_30D 아님)."""
    r = calc(first_movement_date=TODAY - timedelta(days=10), sales_30d=0)
    assert r.code == "INSUFFICIENT_DATA"


# ----- 경계와 우선순위 -----

def test_available_equal_reorder_point_recommends():
    """가용재고 70 == 재주문점 70 → 추천 (10 × 19 + 20 − 70 = 140)."""
    assert calc(stock=70).recommended_quantity == 140


def test_available_one_over_reorder_point_no_recommendation():
    """가용재고 71 > 재주문점 70 → 추천 없음."""
    assert calc(stock=71).recommended_quantity is None


def test_exactly_14_days_is_calculated():
    """첫 입출고 후 정확히 14일 → 계산한다 (13일은 S6 에서 제외)."""
    assert calc(first_movement_date=TODAY - timedelta(days=14)).recommended_quantity == 160


def test_no_history_is_insufficient_data():
    """이력이 하나도 없으면(첫 입출고 날짜 None) INSUFFICIENT_DATA."""
    assert calc(first_movement_date=None, sales_30d=0, stock=0).code == "INSUFFICIENT_DATA"


def test_ceil_6_1_becomes_7():
    """올림 전 6.1 → 7 (반올림이면 6). 판매 1, 리드타임 19, 안전재고 5, 가용 0: 1/30 × 33 + 5 = 6.1."""
    assert calc(sales_30d=1, lead_time=19, safety_stock=5, stock=0).recommended_quantity == 7


def test_exact_integer_is_not_over_ceiled():
    """올림 전이 정확히 31 이면 31 (float 이면 31.000000000000004 → 32). 판매 31, 리드타임 16, 안전재고 0, 가용 0."""
    assert calc(sales_30d=31, lead_time=16, safety_stock=0, stock=0).recommended_quantity == 31


def test_missing_info_wins_over_all():
    """비활성 + 이력 없음 + 판매 0 → MISSING_INFO 하나만."""
    assert calc(supplier_active=False, first_movement_date=None, sales_30d=0).code == "MISSING_INFO"


# ----- 순수성 -----

def test_same_input_same_result_and_args_unchanged():
    """같은 입력으로 두 번 → 같은 결과, 넘긴 값은 그대로."""
    args = dict(BASE)  # 넘길 값 복사
    before = dict(args)  # 호출 전 값
    first = calculate_recommendation(**args)
    second = calculate_recommendation(**args)
    assert first == second
    assert args == before
