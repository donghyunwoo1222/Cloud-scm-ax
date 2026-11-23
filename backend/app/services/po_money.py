"""발주 금액 규칙(순수 함수). DB·FastAPI·모델을 쓰지 않는다. 규칙 전문은 docs/06-system-design/money-rules.md.

핵심: 외화 금액은 Decimal 로 정확히 계산하고, 원화 환산은 총액에서 한 번만 원 미만 버림(ROUND_DOWN)한다.
float 과 파이썬 round() 는 쓰지 않는다. 부가세는 여기서 계산하지 않는다(외화 부가세 기준은 보류, #268).
"""

from decimal import (  # 정확한 십진수 계산 도구
    ROUND_DOWN,  # 0 쪽으로 버림
    Context,  # 계산 규칙 묶음(자릿수·버림 방식·오류로 볼 사건)
    Decimal,  # 정확한 십진수
    DivisionByZero,  # 0 으로 나눔
    Inexact,  # 계산 중 조용히 반올림이 일어남
    InvalidOperation,  # 숫자가 아닌 입력 등
    Overflow,  # 범위 초과
)

# 이 모듈 전용 계산 규칙. 전역 컨텍스트(기본 28자리)는 건드리지 않는다.
# 60자리면 줄 2,000 × 수량 100만 × 단가 약 1억 × 환율 약 1만 곱도 모두 담긴다. 곱셈·덧셈에서 반올림이 필요해지면 Inexact 로 즉시 멈춘다.
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


class MoneyError(ValueError):
    """금액 규칙 위반(잘못된 환율·단가·단위·통화 등)."""


def to_decimal(value) -> Decimal:
    """str·int·Decimal 만 Decimal 로 바꾼다. float·bool 은 TypeError(0.1 같은 부정확한 값이 섞이는 것을 막는다)."""
    if isinstance(value, bool) or not isinstance(
        value, (str, int, Decimal)
    ):  # bool 은 int 의 하위형이라 따로 막는다
        raise TypeError(f"금액은 str·int·Decimal 만 받습니다({type(value).__name__}).")
    try:
        result = CTX.create_decimal(value)  # 60자리를 넘겨 반올림해야 하면 Inexact
    except (InvalidOperation, Inexact) as exc:
        raise MoneyError(f"숫자로 읽을 수 없는 금액입니다: {value!r}") from exc
    if not result.is_finite():  # NaN·Infinity 거절
        raise MoneyError(f"유한한 숫자가 아닙니다: {value!r}")
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
    return (
        value.normalize(CTX).as_tuple().exponent >= -decimals
    )  # 끝자리 0 을 뗀 뒤 소수 자릿수를 센다


def parse_rate(value, currency: str) -> Decimal:
    """환율(기준 단위당 원)을 검사해 Decimal 로 돌려준다. KRW·미지원 통화·0 이하·소수 둘째 자리 초과는 거절."""
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    if currency == "KRW":
        raise MoneyError("원화(KRW)는 환율이 없습니다.")
    rate = to_decimal(value)
    if rate <= 0:
        raise MoneyError("환율은 0보다 커야 합니다.")
    if not _fits_decimals(rate, RATE_DECIMALS):
        raise MoneyError("환율은 소수 둘째 자리까지만 입력할 수 있습니다.")
    return rate


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
    """줄 외화 금액 = 수량(정수) × 외화 단가. 정확한 값이며 반올림하지 않는다. 예) 3 × 0.50 = 1.50."""
    return CTX.multiply(Decimal(_int_of("수량", quantity)), to_decimal(fx_unit_price))


def krw_of(fx_amounts, rate, unit: int) -> int:
    """원화 환산 = (외화 금액 합) × 환율 ÷ 기준 단위, 총액에서 한 번만 원 미만 버림. 예) 3×0.50달러×1,350.25 = 2,025.375 → 2,025."""
    if isinstance(unit, bool) or unit not in (1, 100):  # 1·100 만 허용하면 나눗셈이 항상 정확하다
        raise MoneyError("환율 기준 단위는 1 또는 100 이어야 합니다.")
    rate = to_decimal(rate)
    if rate <= 0:
        raise MoneyError("환율은 0보다 커야 합니다.")
    total = Decimal(0)
    for amount in fx_amounts:  # 줄별로 버리지 않고 정확한 값을 그대로 더한다
        amount = to_decimal(amount)
        if amount < 0:
            raise MoneyError("외화 금액은 0 이상이어야 합니다.")
        total = CTX.add(total, amount)
    exact = CTX.divide(
        CTX.multiply(total, rate), Decimal(unit)
    )  # 여기까지는 모두 정확(아니면 Inexact)
    return int(
        exact.to_integral_value(rounding=ROUND_DOWN)
    )  # 최종 버림만 허용: to_integral_value 는 Inexact 를 내지 않는다


def goods_krw_total(line_fx_amounts, currency: str, rate=None) -> int:
    """품목 원화 합계. KRW 는 환율 없이(rate=None) 합계를 한 번 버림, 외화는 통화의 기준 단위로 krw_of 호출."""
    if currency not in CURRENCIES:
        raise MoneyError(f"지원하지 않는 통화입니다: {currency!r}")
    if currency == "KRW":
        if rate is not None:
            raise MoneyError("원화(KRW)는 환율을 받지 않습니다.")
        return krw_of(
            line_fx_amounts, Decimal(1), 1
        )  # 환율 1 로 합계만 구한다(입고 기준 소수 금액도 한 번 버림)
    return krw_of(line_fx_amounts, parse_rate(rate, currency), CURRENCIES[currency][0])


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


def unit_price_of_box(box_price, pieces_per_box: int) -> Decimal:
    """박스 단가를 낱개 단가로: 10,005원 ÷ 10개입 = 1,000.5원.

    shortcut: 나누어떨어지지 않으면(예 1,000 ÷ 3) MoneyError. 끝자리를 자르면 합계가 정수 경계에서 1원 어긋나므로 PR 1 에서 곱한 뒤 나누는 방식을 정한다.
    """
    pieces = _int_of("박스당 낱개 수", pieces_per_box)
    if pieces == 0:
        raise MoneyError("박스당 낱개 수는 1 이상이어야 합니다.")
    try:
        return CTX.divide(to_decimal(box_price), Decimal(pieces))
    except Inexact as exc:
        raise MoneyError("박스 단가가 낱개 수로 나누어떨어지지 않습니다.") from exc


def received_fx_amount(received_qty: int, price_per_stock_unit) -> Decimal:
    """입고 기준 외화 금액 = 입고 수량 × 재고 단위당 단가. 예) 45개 × 1,000.5 = 45,022.5(원 미만 버림은 krw_of 에서 한 번)."""
    return CTX.multiply(
        Decimal(_int_of("입고 수량", received_qty)), to_decimal(price_per_stock_unit)
    )
