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
    received_fx_amount,
    to_decimal,
    unit_price_of_box,
)


def test_원_미만은_한_번_버린다():
    line = fx_line_amount(3, "0.50")  # 3개 × 0.50달러 = 1.50
    assert line == Decimal("1.50")
    assert krw_of([line], "1350.25", 1) == 2025  # 2,025.375 → 2,025


def test_총액에서_한_번_버리면_줄별_버림보다_2원_크다():
    lines = [fx_line_amount(1, "1")] * 3  # 1달러 3줄
    assert goods_krw_total(lines, "USD", "1350.75") == 4052  # 3 × 1,350.75 = 4,052.25
    assert sum(krw_of([x], "1350.75", 1) for x in lines) == 4050  # 줄별로 버리면 1,350 × 3


def test_엔화는_기준_단위_100():
    assert CURRENCIES["JPY"] == (100, 0)
    assert goods_krw_total([Decimal(10000)], "JPY", "905.12") == 90512  # 10,000 × 905.12 ÷ 100


def test_입고_기준_박스_줄():
    per_piece = unit_price_of_box(10005, 10)  # 박스 10,005원 ÷ 10개입
    assert per_piece == Decimal("1000.5")
    amount = received_fx_amount(45, per_piece)
    assert amount == Decimal("45022.5")
    assert goods_krw_total([amount], "KRW") == 45022  # 한 번 버림


def test_원가_합산():
    assert cost_total(1_380_000, 120_000, [10_000, 20_000]) == (1_530_000, [])


def test_운송비_미입력과_0은_다르다():
    assert cost_total(1_000, None, []) == (1_000, ["freight"])  # 합계는 계산, 미입력 표시
    assert cost_total(1_000, 0, []) == (1_000, [])  # 0 은 입력한 값


def test_기존_원화_회귀():
    lines = [fx_line_amount(1, 1005)] * 3  # 1,005원 × 3줄
    supply = goods_krw_total(lines, "KRW")
    assert supply == 3015
    assert vat_of(supply) == 301  # 기존 부가세 규칙과 같은 값(이 PR 은 부가세를 만들지 않는다)


def test_상한에서도_조용한_반올림이_없다():
    # 2,000줄 × 수량 1,000,000 × 단가 99,999,999.99 × 환율 9,999.99. Inexact 가 나면 CTX 가 예외를 내 이 테스트가 실패한다.
    line = fx_line_amount(1_000_000, check_fx_price("99999999.99", "USD"))
    rate = parse_rate("9999.99", "USD")
    expected = floor(
        Fraction(2000 * 1_000_000 * 9_999_999_999, 100) * Fraction(999_999, 100)
    )  # 분수로 따로 계산한 정답
    assert goods_krw_total([line] * 2000, "USD", rate) == expected
    assert decimal.getcontext().prec == 28  # 전역 컨텍스트는 그대로(이 모듈은 자기 컨텍스트만 쓴다)


@pytest.mark.parametrize(
    "call, error",
    [
        (lambda: to_decimal(1.5), TypeError),  # float
        (lambda: fx_line_amount(1, 0.5), TypeError),  # float 단가
        (lambda: fx_line_amount(True, 1), TypeError),  # bool 수량
        (lambda: fx_line_amount(-1, 1), MoneyError),  # 음수 수량
        (lambda: check_fx_price("0.035", "USD"), MoneyError),  # 센트 미만 단가
        (lambda: check_fx_price("0.5", "JPY"), MoneyError),  # 엔 소수 단가
        (lambda: check_fx_price("-1", "USD"), MoneyError),  # 음수 단가
        (lambda: parse_rate("0", "USD"), MoneyError),  # 환율 0
        (lambda: parse_rate("-1", "USD"), MoneyError),  # 환율 음수
        (lambda: parse_rate("1350.255", "USD"), MoneyError),  # 소수 셋째 자리
        (lambda: parse_rate("1350", "KRW"), MoneyError),  # 원화는 환율 없음
        (lambda: krw_of([Decimal(1)], "1350", 50), MoneyError),  # 기준 단위 50
        (lambda: goods_krw_total([Decimal(1)], "GBP", "1"), MoneyError),  # 미지원 통화
        (lambda: parse_rate("1", "GBP"), MoneyError),
        (lambda: goods_krw_total([Decimal(1)], "KRW", "1"), MoneyError),  # 원화에 환율을 줌
        (lambda: unit_price_of_box(1000, 3), MoneyError),  # 나누어떨어지지 않음
        (lambda: to_decimal("abc"), MoneyError),
    ],
)
def test_잘못된_입력은_거절한다(call, error):
    with pytest.raises(error):
        call()


def test_끝자리_0이_있는_환율은_허용한다():
    assert parse_rate("1350.250", "USD") == Decimal("1350.25")
