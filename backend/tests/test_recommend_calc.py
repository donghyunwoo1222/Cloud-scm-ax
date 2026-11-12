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


# ----- 발주단위 올림 S15~S19 (#187): 기본단위로 계산한 뒤 마지막에 발주단위 배수로 올린다 -----

def test_s15_shortage_230_becomes_3_boxes():
    """S15: 부족 230개(안전재고 40, 가용 0: 10 × 19 + 40 − 0), 1BOX = 100개 → 3BOX, 도착 300개 (70개 더 온다)."""
    r = calc(safety_stock=40, stock=0, unit_factor=100, order_unit="BOX")
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity) == (230, 3, 300)
    assert r.reason.endswith("추천 수량은 230개입니다. 발주단위로 올림하면 3BOX(300개)입니다.")


def test_s16_exact_multiple_is_not_over_ceiled():
    """S16: 부족 200개(가용 30), 1BOX = 100개 → 2BOX, 도착 200개 (나누어떨어지면 더 올리지 않는다)."""
    r = calc(safety_stock=40, stock=30, unit_factor=100, order_unit="BOX")
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity) == (200, 2, 200)


def test_s17_factor_1_is_unchanged():
    """S17: 환산계수 1이면 결과가 변경 전과 완전히 같다 (S1 160, S12 7, 이유 문구 포함)."""
    assert calc(unit_factor=1, order_unit="개") == calc()
    s1, s12 = calc(unit_factor=1), calc(unit_factor=1, sales_30d=7, safety_stock=2, stock=0)
    assert (s1.order_units, s1.arrival_quantity, s12.order_units, s12.arrival_quantity) == (160, 160, 7, 7)
    assert "발주단위" not in s1.reason


def test_s19_large_factor_bag_25000g():
    """S19: 1BAG = 25000g, 부족 25001g(안전재고 24811, 가용 0) → 2BAG, 도착 50000g. 1g 넘으면 한 봉지 더."""
    r = calc(safety_stock=24811, stock=0, unit="g", unit_factor=25000, order_unit="BAG")
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity) == (25001, 2, 50000)


# ----- 최소 주문량 S20~S23 (#194): 발주단위로 올린 뒤 MOQ와 비교해 큰 쪽 -----

def test_s20_shortage_1_box_moq_5_becomes_5_boxes():
    """S20: 일평균 1, 가용 5 → 부족 14개 → 1BOX(1BOX = 100개), MOQ 5BOX → 5BOX, 도착 500개. 늘어난 양을 문구로 알린다."""
    r = calc(sales_30d=30, safety_stock=0, stock=5, unit_factor=100, order_unit="BOX", min_order_units=5)
    assert (r.recommended_quantity, r.packed_units, r.order_units, r.arrival_quantity, r.moq_applied) == (14, 1, 5, 500, True)
    assert r.reason.endswith("추천 수량은 14개입니다. 발주단위로 올림하면 1BOX(100개)입니다. "
                             "최소 주문량 5BOX를 적용해 5BOX(500개)를 추천합니다. 부족분보다 486개 많습니다.")


def test_s21_shortage_8_boxes_over_moq_5_stays_8():
    """S21: 부족 790개(안전재고 600, 가용 0) → 8BOX, MOQ 5BOX 보다 크므로 8BOX 그대로. 문구에 최소 주문량이 없다."""
    r = calc(safety_stock=600, stock=0, unit_factor=100, order_unit="BOX", min_order_units=5)
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity, r.moq_applied) == (790, 8, 800, False)
    assert "최소 주문량" not in r.reason
    assert r.reason == calc(safety_stock=600, stock=0, unit_factor=100, order_unit="BOX").reason  # MOQ 없을 때와 같은 문구


def test_s22_no_moq_is_unchanged():
    """S22: MOQ 없음이면 S1·S12·S15 결과와 문구가 변경 전과 같다."""
    assert calc(min_order_units=None) == calc()
    s12 = calc(sales_30d=7, safety_stock=2, stock=0)
    assert (s12.order_units, s12.moq_applied) == (7, False)
    s15 = calc(safety_stock=40, stock=0, unit_factor=100, order_unit="BOX")
    assert (s15.order_units, s15.arrival_quantity, s15.moq_applied) == (3, 300, False)


def test_s23_moq_without_box_settings_uses_base_unit():
    """S23: 박스 설정 없음(환산계수 1), 부족 7개(S12), MOQ 20 → 20개. 환산 괄호는 같은 숫자라 쓰지 않는다."""
    r = calc(sales_30d=7, safety_stock=2, stock=0, min_order_units=20)
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity, r.moq_applied) == (7, 20, 20, True)
    assert r.reason.endswith("추천 수량은 7개입니다. 최소 주문량 20개를 적용해 20개를 추천합니다. 부족분보다 13개 많습니다.")


def test_moq_equal_to_packed_units_is_not_applied():
    """MOQ가 발주단위 올림 결과와 같으면(부족 230개 → 3BOX, MOQ 3) 늘어난 게 아니라 문구를 더하지 않는다."""
    r = calc(safety_stock=40, stock=0, unit_factor=100, order_unit="BOX", min_order_units=3)
    assert (r.order_units, r.moq_applied) == (3, False) and "최소 주문량" not in r.reason


def test_no_recommendation_ignores_moq():
    """추천하지 않는 품목(S2)은 MOQ가 있어도 발주단위 수가 None."""
    r = calc(stock=150, min_order_units=5)
    assert (r.order_units, r.moq_applied) == (None, False)


def test_fraction_ceil_then_order_unit():
    """분수 → 추천 수량 올림 → 발주단위 올림: S12 6.43 → 7개, 1팩 = 5개 → 2팩(10개). 부동소수점을 쓰지 않는다."""
    r = calc(sales_30d=7, safety_stock=2, stock=0, unit_factor=5)
    assert (r.recommended_quantity, r.order_units, r.arrival_quantity) == (7, 2, 10)


def test_no_recommendation_has_no_order_units():
    """추천하지 않는 품목(S2)은 발주단위 수·도착 수량도 None."""
    r = calc(stock=150, unit_factor=100)
    assert (r.order_units, r.arrival_quantity) == (None, None)


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
