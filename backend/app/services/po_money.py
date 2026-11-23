"""발주 금액 규칙(순수 함수). DB·FastAPI·모델을 쓰지 않는다. 규칙 전문은 docs/06-system-design/money-rules.md.

핵심: 금액은 정확한 값(Decimal·Fraction)으로 계산하고, 원화 환산은 총액에서 한 번만 원 미만 버림한다.
float 과 파이썬 round() 는 쓰지 않는다. 부가세는 여기서 계산하지 않는다(외화 부가세 기준은 보류, #268).
"""

import re  # 금액 문자열 모양 검사
from decimal import (  # 정확한 십진수 계산 도구
    ROUND_DOWN,  # 0 쪽으로 버림
    Context,  # 계산 규칙 묶음(자릿수·버림 방식·오류로 볼 사건)
    Decimal,  # 정확한 십진수
    DivisionByZero,  # 0 으로 나눔
    Inexact,  # 계산 중 조용히 반올림이 일어남
    InvalidOperation,  # 숫자가 아닌 입력 등
    Overflow,  # 범위 초과
)
from fractions import Fraction  # 정확한 분수(나눗셈도 오차 없이)
from math import floor  # 내림(음수가 없으므로 버림과 같다)

# 이 모듈 전용 계산 규칙. 전역 컨텍스트(기본 28자리)는 건드리지 않는다.
# 계획의 상한(줄 2,000 × 수량 100만 × 단가 약 1억 × 환율 약 1만) 안에서는 Inexact 없이 정확하다.
# 60자리를 넘겨 반올림이 필요해지면 조용히 넘어가지 않고 오류로 멈춘다(입력은 MoneyError 로 바뀐다).
CTX = Context(
    prec=60, rounding=ROUND_DOWN, traps=[Inexact, InvalidOperation, DivisionByZero, Overflow]
)

# 통화 → (환율 기준 단위, 소수 자릿수). 환율은 "기준 단위당 원"(예: 100엔 = 905.12원)
CURRENCIES: dict[str, tuple[int, int]] = {
    "KRW": (1, 0),
    "USD": (1, 2),
    "EUR": (1, 2),
    "JPY": (100, 0),
    "CNY": (1, 2),
    "VND": (100, 0),
}
RATE_DECIMALS = 2  # 환율은 소수 둘째 자리까지
_PLAIN_NUMBER = re.compile(
    r"[0-9]+(\.[0-9]+)?", re.ASCII
)  # 부호·지수·비ASCII 숫자 없는 평범한 숫자


class MoneyError(ValueError):
    """금액 규칙 위반(잘못된 환율·단가·단위·통화 등)."""


def to_decimal(value) -> Decimal:
    """str·int·Decimal 만 Decimal 로 바꾼다. float·bool 은 TypeError(0.1 같은 부정확한 값이 섞이는 것을 막는다).

    문자열은 "1350", "1350.250" 모양만 허용한다(지수 "1e3", 아라비아·전각 숫자, 부호 "-0" 은 MoneyError).
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        # bool 은 int 의 하위형이라 따로 막는다
        raise TypeError(f"금액은 str·int·Decimal 만 받습니다({type(value).__name__}).")
    if isinstance(value, str) and not _PLAIN_NUMBER.fullmatch(value):
        raise MoneyError(f"숫자로 읽을 수 없는 금액입니다: {value!r}")
    try:
        result = CTX.create_decimal(value)  # 60자리를 넘겨 반올림해야 하면 Inexact
    except (InvalidOperation, Inexact) as exc:
        raise MoneyError(f"숫자로 읽을 수 없는 금액입니다: {value!r}") from exc
    if not result.is_finite():  # NaN·Infinity 거절
        raise MoneyError(f"유한한 숫자가 아닙니다: {value!r}")
    if result.is_zero() and result.is_signed():  # -0, -0E+2 거절
        raise MoneyError(f"음수 0 은 받지 않습니다: {value!r}")
    return result


def _int_of(name: str, value) -> int:
    """수량·원화 금액처럼 정수여야 하는 값을 검사한다(bool·float 거절, 음수 거절)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} 은 정수여야 합니다({type(value).__name__}).")
    if value < 0:
        raise MoneyError(f"{name} 은 0 이상이어야 합니다.")
    return value


def _fits_decimals(value: Decimal, decimals: int) -> bool:
    """값이 소수 decimals 자리 이내인지(끝자리 0 은 허용: 1350.250 은 둘째 자리 이내)."""
    # 끝자리 0 을 뗀 뒤 소수 자릿수를 센다
    return value.normalize(CTX).as_tuple().exponent >= -decimals


def _check_rate(value) -> Decimal:
    """환율 값 검사(0 초과, 소수 둘째 자리 이내). parse_rate 와 krw_of 가 함께 쓴다."""
    rate = to_decimal(value)
    if rate <= 0:
        raise MoneyError("환율은 0보다 커야 합니다.")
    if not _fits_decimals(rate, RATE_DECIMALS):
        raise MoneyError("환율은 소수 둘째 자리까지만 입력할 수 있습니다.")
    return rate


def parse_rate(value, currency: str) -> Decimal:
    """환율(기준 단위당 원)을 검사해 Decimal 로 돌려준다. KRW·미지원 통화·0 이하·소수 둘째 자리 초과는 거절."""
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    if currency == "KRW":
        raise MoneyError("원화(KRW)는 환율이 없습니다.")
    return _check_rate(value)


def check_fx_price(price, currency: str) -> Decimal:
    """외화 단가를 검사한다. 음수, 통화 소수 자릿수 초과(USD 0.035, JPY 0.5)는 거절."""
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    decimals = CURRENCIES[currency][1]
    value = to_decimal(price)
    if value < 0:
        raise MoneyError("단가는 0 이상이어야 합니다.")
    if not _fits_decimals(value, decimals):
        raise MoneyError(f"{currency} 단가는 소수 {decimals}자리까지만 입력할 수 있습니다.")
    return value


def fx_line_amount(quantity: int, fx_unit_price) -> Decimal:
    """줄 외화 금액 = 수량(정수) × 외화 단가. 정확한 값이며 반올림하지 않는다. 예) 3 × 0.50 = 1.50.

    자릿수 한도(60자리)를 넘어 정확하게 계산할 수 없으면 MoneyError.
    """
    qty = _int_of("수량", quantity)
    price = to_decimal(fx_unit_price)
    try:
        return CTX.multiply(
            Decimal(qty), price
        )  # Decimal(int) 는 정확, 곱셈은 한도를 넘으면 Inexact
    except (Inexact, InvalidOperation, Overflow) as exc:
        raise MoneyError("금액이 너무 커서 정확히 계산할 수 없습니다.") from exc


def krw_of(fx_amounts, rate, unit: int) -> int:
    """원화 환산 = (외화 금액 합) × 환율 ÷ 기준 단위, 총액에서 한 번만 원 미만 버림. 예) 3×0.50달러×1,350.25 = 2,025.375 → 2,025."""
    if isinstance(unit, bool) or unit not in (1, 100):  # 1·100 만 허용하면 나눗셈이 항상 정확하다
        raise MoneyError("환율 기준 단위는 1 또는 100 이어야 합니다.")
    rate = _check_rate(rate)
    amounts = [to_decimal(a) for a in fx_amounts]  # 줄별로 버리지 않고 정확한 값을 그대로 더한다
    if any(a < 0 for a in amounts):
        raise MoneyError("외화 금액은 0 이상이어야 합니다.")
    try:
        total = Decimal(0)
        for amount in amounts:
            total = CTX.add(total, amount)
        # 여기까지는 모두 정확(아니면 Inexact)
        exact = CTX.divide(CTX.multiply(total, rate), Decimal(unit))
    except (Inexact, InvalidOperation, Overflow) as exc:
        raise MoneyError("금액이 너무 커서 정확히 계산할 수 없습니다.") from exc
    # 최종 버림만 허용: to_integral_value 는 Inexact 를 내지 않는다
    return int(exact.to_integral_value(rounding=ROUND_DOWN))


def goods_krw_total(line_fx_amounts, currency: str, rate=None) -> int:
    """품목 원화 합계. KRW 는 환율 없이(rate=None) 합계를 한 번 버림, 외화는 통화의 기준 단위로 krw_of 호출."""
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    if currency == "KRW":
        if rate is not None:
            raise MoneyError("원화(KRW)는 환율을 받지 않습니다.")
        return krw_of(line_fx_amounts, Decimal(1), 1)  # 환율 1 로 합계만 한 번 버린다
    return krw_of(line_fx_amounts, parse_rate(rate, currency), CURRENCIES[currency][0])


def received_goods_krw(lines, currency: str, rate=None) -> int:
    """입고 기준 품목 원화 합계. 줄 = (입고한 재고 단위 수, 가격, 그 가격이 몇 재고 단위당인지).

    낱개 단가 줄은 per=1, 박스 단가 줄은 per=박스당 낱개 수. 줄 금액 = 입고 수 × 가격 ÷ per 를 분수로 정확히 구해
    모두 더하고(외화면 × 환율 ÷ 기준 단위) 맨 끝에서 한 번만 버린다. 발주 시 총액(goods_krw_total)과 같은 규칙이다.
    예) 1,000원 3개입 박스, 4개 입고 → 4 × 1,000 ÷ 3 = 1,333.33… → 1,333원.
    """
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    total = Fraction(0)
    for received_qty, price, per in lines:
        qty = _int_of("입고 수량", received_qty)  # 0 은 허용
        per = _int_of("가격 기준 재고 단위 수", per)
        if per == 0:
            raise MoneyError("가격 기준 재고 단위 수는 1 이상이어야 합니다.")
        total += (
            Fraction(qty) * Fraction(check_fx_price(price, currency)) / per
        )  # Fraction(Decimal) 은 정확
    if currency == "KRW":
        if rate is not None:
            raise MoneyError("원화(KRW)는 환율을 받지 않습니다.")
        return floor(total)
    unit = CURRENCIES[currency][0]
    return floor(total * Fraction(parse_rate(rate, currency)) / unit)


def cost_total(goods_krw: int, freight: int | None, extra_amounts) -> tuple[int, list[str]]:
    """원가 = 품목 원화 합계 + 운송비 + 부대비용 합계(부가세 미포함). 돌려주는 값: (합계, 미입력 항목 목록).

    freight=None 은 미입력(0 으로 계산하되 missing 에 "freight"), 0 은 입력한 값이라 missing 이 아니다.
    """
    missing: list[str] = []
    if freight is None:
        missing.append("freight")
        freight = 0
    total = _int_of("품목 원화 합계", goods_krw) + _int_of("운송비", freight)
    for extra in extra_amounts:
        total += _int_of("부대비용", extra)
    return total, missing
