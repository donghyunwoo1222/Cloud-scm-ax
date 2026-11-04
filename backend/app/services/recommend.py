"""발주 추천 계산 (F8, AX 1차). DB·현재 시각·네트워크를 쓰지 않는 순수 함수만 둔다.

조회(현재고, 정정을 뺀 30일 순판매, 진행 중 발주, 첫 입출고 날짜)는 #39 의 추천 service 가 해서 숫자로 넘긴다.
공식은 CLAUDE.md §5, 제외 순서·이유 문구는 docs/04-ax-design/ax-design.md 를 따른다.
"""

import math  # 추천 수량을 올림(ceil)할 때 쓴다
from dataclasses import dataclass  # 결과 묶음 모양
from datetime import date  # 오늘·첫 입출고 날짜 타입
from fractions import (
    Fraction,  # 정확한 분수 계산 (float 오차로 31 이 31.000000000000004 → 올림 32 가 되는 것을 막는다)
)

SALES_WINDOW_DAYS = 30  # 일평균을 구하는 기간: 오늘 포함 30일 (오늘−29일 ~ 오늘)
MIN_HISTORY_DAYS = 14  # 데이터 부족 기준: (오늘 − 첫 입출고) < 14일이면 계산하지 않는다 (확정)
REPLENISH_CYCLE_DAYS = 14  # 보충 주기 14일 (임시값, 인터뷰·측정 후 조정. 바꿀 곳은 여기 한 곳)

EXCLUDED_MESSAGES = {  # 제외 코드 → 화면에 보여 줄 문장 (api-design.md §5)
    "MISSING_INFO": "기본 공급업체가 비활성입니다. 품목 정보를 확인하세요",  # S7
    "INSUFFICIENT_DATA": "데이터 부족",  # S6, S14
    "NO_SALES_30D": "최근 30일 판매 없음",  # S5
}


@dataclass(frozen=True)  # frozen: 만든 뒤 값을 못 바꾼다
class Excluded:
    """계산하지 않은 품목: 제외 코드와 안내 문장."""

    code: str  # MISSING_INFO / INSUFFICIENT_DATA / NO_SALES_30D
    message: str  # 화면 안내 문장


@dataclass(frozen=True)
class Recommendation:
    """계산한 품목: 추천 여부와 상관없이 계산 숫자를 모두 담는다(#39 재고 상태·대시보드 부족 표시가 같은 값을 쓰게)."""

    avg_daily_sales: Fraction  # 일평균 판매량, 분수 그대로 (예: 7/30 = 0.233…)
    available: int  # 가용재고 = 현재고 + 진행 중 발주
    reorder_point: Fraction  # 재주문점, 분수 그대로 (예: 19/6 = 3.17)
    recommended_quantity: int | None  # 추천 수량(올림한 정수). 추천하지 않으면 None (= 부족 아님)
    reason: str | None  # 이유 문구. 추천하지 않으면 None


def calculate_recommendation(
    today: date,  # 오늘 날짜 (인자로 받아 테스트가 날짜를 고정한다)
    first_movement_date: date | None,  # 이 품목의 첫 입출고 날짜. 이력이 없으면 None
    supplier_active: bool,  # 기본 공급업체가 활성인지
    sales_30d: int,  # 최근 30일 SALE 순판매 합계 (SALE − 그 SALE 을 가리키는 정정, 기간은 원래 판매 날짜)
    stock: int,  # 현재고 (이력 합계)
    in_transit: int,  # ORDERED 발주의 미입고 수량 합계 (CANCELLED 는 넣지 않는다)
    lead_time: int,  # 기본 공급업체의 리드타임(일)
    safety_stock: int,  # 품목의 안전재고
    cycle: int = REPLENISH_CYCLE_DAYS,  # 보충 주기(일)
) -> Recommendation | Excluded:
    """품목 하나의 추천을 계산한다. 같은 입력이면 항상 같은 결과를 돌려준다."""
    # 제외 검사: 위에서부터 먼저 걸린 하나만 돌려준다 (MISSING_INFO → INSUFFICIENT_DATA → NO_SALES_30D, 확정)
    if not supplier_active:  # 1순위: 기본 공급업체가 비활성이면
        return _excluded("MISSING_INFO")  # S7
    if first_movement_date is None or (today - first_movement_date).days < MIN_HISTORY_DAYS:  # 2순위: 이력 없음 또는 14일 미만
        return _excluded("INSUFFICIENT_DATA")  # S6 (13일 전 → 제외, 14일 전 → 계산), S14
    if sales_30d <= 0:  # 3순위: 최근 30일 순판매가 없으면
        return _excluded("NO_SALES_30D")  # S5

    avg = Fraction(sales_30d, SALES_WINDOW_DAYS)  # 일평균, 분수 그대로 (예: 300 ÷ 30 = 10, 7 ÷ 30 = 0.233…)
    available = stock + in_transit  # 가용재고 (예: 현재고 50 + 오는 중 0 = 50, 오는 중 160 이면 210)
    lead_demand = avg * lead_time  # 리드타임 동안 팔릴 양 (예: 10 × 5 = 50)
    reorder_point = lead_demand + safety_stock  # 재주문점 (예: 50 + 20 = 70)
    if available > reorder_point:  # 가용재고가 재주문점보다 크면 (같으면 추천한다)
        return Recommendation(avg, available, reorder_point, None, None)  # 계산 숫자만 돌려주고 추천은 없음 (S2, S3)

    raw = avg * (lead_time + cycle) + safety_stock - available  # 올림 전 추천 수량 (예: 10 × (5 + 14) + 20 − 50 = 160)
    quantity = math.ceil(raw)  # 마지막에만 올림 (예: 7/30 × 19 + 2 − 0 = 6.43 → 7)
    # 여기까지 오면 raw = avg × cycle + (재주문점 − 가용재고) 이고 avg > 0, 재주문점 ≥ 가용재고라 항상 1 이상이다.
    # 이슈 본문의 "0 이하면 추천 없음"은 cycle 을 0 이하로 바꿀 때를 대비한 방어 줄로 남긴다.
    if quantity <= 0:
        return Recommendation(avg, available, reorder_point, None, None)

    reason = (  # 정해진 문장 틀에 계산 숫자만 끼워 넣는다 (LLM 아님, 확정)
        f"최근 30일 하루 평균 {_num(avg)}개가 팔렸고 리드타임은 {lead_time}일입니다. "
        f"리드타임 동안 {_num(lead_demand)}개가 필요하고 안전재고 {safety_stock}개를 더하면 {_num(reorder_point)}개입니다. "
        f"지금 가용재고는 {available}개라서 발주를 추천합니다. 추천 수량은 {quantity}개입니다."
    )  # 예) 하루 평균 10개 … 50개가 필요 … 70개입니다. 가용재고는 50개 … 추천 수량은 160개입니다.
    return Recommendation(avg, available, reorder_point, quantity, reason)


def _excluded(code: str) -> Excluded:
    """제외 코드로 결과를 만든다."""
    return Excluded(code, EXCLUDED_MESSAGES[code])


def _num(x: Fraction) -> str:
    """문구용 숫자: 정수면 그대로(70), 소수면 첫째 자리까지(3.1666… → 3.2)."""
    return str(x.numerator) if x.denominator == 1 else f"{float(x):.1f}"
