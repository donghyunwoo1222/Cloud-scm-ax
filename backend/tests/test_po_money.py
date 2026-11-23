"""발주 금액 규칙(po_money) 단위 테스트. DB 가 필요 없다. 숫자는 docs/06-system-design/money-rules.md 의 표와 같다."""

import decimal  # 전역 컨텍스트가 그대로인지 확인
from decimal import Decimal
from fractions import Fraction  # 정확한 분수로 기대값을 따로 계산
from math import floor

import pytest

from app.services.po_document import vat_of  # 기존 부가세 규칙(회귀 비교용, 읽기만)
from app.services.po_money import (
    CURRENCIES,
    MoneyError,
    check_fx_price,
    cost_total,
    fx_line_amount,
    goods_krw_total,
    krw_of,
    parse_rate,
    received_goods_krw,
    to_decimal,
)


def test_floor_once_below_one_won():
    """원 미만은 한 번 버린다: 3개 × 0.50달러 × 1,350.25 = 2,025.375 → 2,025."""
    line = fx_line_amount(3, "0.50")
    assert line == Decimal("1.50")
    assert krw_of([line], "1350.25", 1) == 2025


def test_floor_not_round_when_fraction_above_half():
    """.5 보다 큰 경우도 버림이다(반올림·은행가 반올림이면 2,026): 3 × 0.50 × 1,350.45 = 2,025.675 → 2,025."""
    line = fx_line_amount(3, "0.50")
    assert krw_of([line], "1350.45", 1) == 2025
    assert floor(Fraction(3) * Fraction("0.50") * Fraction("1350.45")) == 2025  # 분수로 교차 확인
    # 같은 숫자를 입고 기준 함수로도(박스 줄 아님, per=1)
    assert received_goods_krw([(3, "0.50", 1)], "USD", "1350.45") == 2025


def test_total_floor_beats_line_floor_by_two_won():
    """1달러 3줄 × 환율 1,350.75: 총액에서 한 번 버리면 4,052원, 줄별로 버리면 4,050원."""
    lines = [fx_line_amount(1, "1")] * 3
    assert goods_krw_total(lines, "USD", "1350.75") == 4052
    assert sum(krw_of([x], "1350.75", 1) for x in lines) == 4050


def test_jpy_rate_unit_100():
    """엔화는 기준 단위 100: 10,000엔 × 905.12 ÷ 100 = 90,512원."""
    assert CURRENCIES["JPY"] == (100, 0)
    assert goods_krw_total([Decimal(10000)], "JPY", "905.12") == 90512


def test_cost_total_adds_freight_and_extras():
    """원가 = 품목 1,380,000 + 운송비 120,000 + 부대비용 30,000 = 1,530,000."""
    assert cost_total(1_380_000, 120_000, [10_000, 20_000]) == (1_530_000, [])


def test_freight_none_differs_from_zero():
    """운송비 미입력(None)은 missing 에 표시하고, 0 은 입력한 값이다."""
    assert cost_total(1_000, None, []) == (1_000, ["freight"])
    assert cost_total(1_000, 0, []) == (1_000, [])


def test_krw_regression_with_existing_vat():
    """기존 원화: 1,005원 × 3줄 = 3,015원, 기존 vat_of 는 301(이 PR 은 부가세를 만들지 않는다)."""
    lines = [fx_line_amount(1, 1005)] * 3
    supply = goods_krw_total(lines, "KRW")
    assert supply == 3015
    assert vat_of(supply) == 301


def test_upper_limit_is_exact():
    """2,000줄 × 수량 1,000,000 × 단가 99,999,999.99 × 환율 9,999.99 도 Inexact 없이 정확하다(분수로 교차 확인)."""
    line = fx_line_amount(1_000_000, check_fx_price("99999999.99", "USD"))
    rate = parse_rate("9999.99", "USD")
    expected = floor(Fraction(2000 * 1_000_000 * 9_999_999_999, 100) * Fraction(999_999, 100))
    assert goods_krw_total([line] * 2000, "USD", rate) == expected
    assert decimal.getcontext().prec == 28  # 전역 컨텍스트는 그대로(이 모듈은 자기 컨텍스트만 쓴다)


# ---- 입고 기준 계산(received_goods_krw) ----


def test_received_krw_box_three_per_box():
    """KRW 1,000원짜리 3개입 박스, 4개 입고 → 4,000/3 = 1,333.33… → 1,333원."""
    assert received_goods_krw([(4, 1000, 3)], "KRW") == 1333
    assert floor(Fraction(4 * 1000, 3)) == 1333


def test_received_krw_box_half_won():
    """KRW 박스 단가 10,005원, 10개입, 45개 입고 → 45,022.5 → 45,022원."""
    assert received_goods_krw([(45, 10005, 10)], "KRW") == 45022


def test_received_floor_not_round_above_half():
    """KRW 1,000원 3개입 박스, 5개 입고 → 1,666.67 → 1,666원(반올림이면 1,667)."""
    assert received_goods_krw([(5, 1000, 3)], "KRW") == 1666


def test_received_usd_box():
    """USD 박스 10.00달러, 3개입, 5개 입고, 환율 1,350.25 → 50/3 × 1,350.25 = 22,504.17 → 22,504원."""
    expected = floor(Fraction(5) * Fraction("10.00") / 3 * Fraction("1350.25"))
    assert expected == 22504
    assert received_goods_krw([(5, "10.00", 3)], "USD", "1350.25") == 22504


@pytest.mark.parametrize(
    "currency, price, qty_boxes, per, rate",
    [("KRW", 10005, 3, 10, None), ("USD", "10.00", 4, 3, "1350.25"), ("JPY", 905, 2, 6, "905.12")],
)
def test_full_receipt_equals_order_total(currency, price, qty_boxes, per, rate):
    """박스를 전부 입고하면(박스 수 × per 개) 입고 기준 금액이 발주 시 총액(수량 × 박스 단가)과 같다."""
    ordered = goods_krw_total([fx_line_amount(qty_boxes, price)], currency, rate)
    received = received_goods_krw([(qty_boxes * per, price, per)], currency, rate)
    assert received == ordered


def test_received_mixed_piece_and_box_lines():
    """낱개 줄 3개 × 1,005원 + 박스 줄(1,000원 3개입 4개 입고) = 3,015 + 1,333.33 → 4,348원."""
    assert received_goods_krw([(3, 1005, 1), (4, 1000, 3)], "KRW") == 4348


def test_received_sums_fractions_before_flooring():
    """줄마다 버리면 3,999원, 분수를 모두 더해 마지막에 한 번 버리면 4,000원."""
    lines = [(4, 1000, 3)] * 3  # 각 1,333.33…, 합 4,000
    assert received_goods_krw(lines, "KRW") == 4000
    assert sum(received_goods_krw([line], "KRW") for line in lines) == 3999


def test_received_zero_qty_allowed():
    assert received_goods_krw([(0, 1000, 3)], "KRW") == 0


# ---- 거절 ----


@pytest.mark.parametrize(
    "call, error",
    [
        (lambda: to_decimal(1.5), TypeError),  # float
        (lambda: fx_line_amount(1, 0.5), TypeError),  # float 단가
        (lambda: fx_line_amount(True, 1), TypeError),  # bool 수량
        (lambda: fx_line_amount(-1, 1), MoneyError),  # 음수 수량
        (lambda: fx_line_amount(10**70 + 1, "1.11"), MoneyError),  # 곱셈이 자릿수 한도 초과
        (lambda: check_fx_price("0.035", "USD"), MoneyError),  # 센트 미만 단가
        (lambda: check_fx_price("0.5", "JPY"), MoneyError),  # 엔 소수 단가
        (lambda: check_fx_price("-1", "USD"), MoneyError),  # 음수 단가
        (lambda: parse_rate("0", "USD"), MoneyError),  # 환율 0
        (lambda: parse_rate("-1", "USD"), MoneyError),  # 환율 음수
        (lambda: parse_rate("1350.255", "USD"), MoneyError),  # 소수 셋째 자리
        (lambda: krw_of([Decimal(1)], "1350.255", 1), MoneyError),  # krw_of 도 셋째 자리 거절
        (lambda: parse_rate("1350", "KRW"), MoneyError),  # 원화는 환율 없음
        (lambda: krw_of([Decimal(1)], "1350", 50), MoneyError),  # 기준 단위 50
        (lambda: goods_krw_total([Decimal(1)], "GBP", "1"), MoneyError),  # 미지원 통화
        (lambda: parse_rate("1", "GBP"), MoneyError),
        (lambda: goods_krw_total([Decimal(1)], "KRW", "1"), MoneyError),  # 원화에 환율을 줌
        (lambda: received_goods_krw([(1, 1000, 0)], "KRW"), MoneyError),  # per 0
        (lambda: received_goods_krw([(-1, 1000, 1)], "KRW"), MoneyError),  # 음수 입고 수량
        (lambda: received_goods_krw([(1, 0.5, 1)], "KRW"), TypeError),  # float 가격
        (lambda: received_goods_krw([(1, "0.5", 1)], "JPY", "905.12"), MoneyError),  # 엔 소수 가격
        (lambda: received_goods_krw([(1, 1000, 1)], "KRW", "1"), MoneyError),  # 원화에 환율
        (lambda: received_goods_krw([(1, 1000, 1)], "USD"), TypeError),  # 외화에 환율 없음
        (lambda: to_decimal("abc"), MoneyError),
        (lambda: to_decimal("1" * 61), MoneyError),  # 61자리 문자열
        (lambda: to_decimal(10**61 + 1), MoneyError),  # 61자리 정수
    ],
)
def test_rejects_bad_input(call, error):
    with pytest.raises(error):
        call()


@pytest.mark.parametrize(
    "bad",
    ["1e3", "1E+2", "١٣٥٠", "１３５０", "-0", "-1", "+1", " 1", "1.", ".5", "", "NaN", "Infinity"]
    + [Decimal("NaN"), Decimal("Infinity"), Decimal("-0"), Decimal("-0E+2")],
)
def test_to_decimal_rejects_odd_forms(bad):
    """지수 표기, 아라비아·전각 숫자, 부호, NaN·Infinity, 음수 0 은 거절한다."""
    with pytest.raises(MoneyError):
        to_decimal(bad)


@pytest.mark.parametrize(
    "ok, expected",
    [
        ("1350", Decimal(1350)),
        ("1350.250", Decimal("1350.250")),
        (7, Decimal(7)),
        (Decimal("1E+2"), Decimal(100)),
    ],
)
def test_to_decimal_accepts_plain_forms(ok, expected):
    assert to_decimal(ok) == expected


def test_trailing_zero_rate_allowed():
    assert parse_rate("1350.250", "USD") == Decimal("1350.25")
