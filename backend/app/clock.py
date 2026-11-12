"""오늘 날짜. 날짜 경계(입출고일 기본값, 최근 30일 등)는 회사 시간대 기준이다(api-design.md, 기본 Asia/Seoul)."""

from datetime import date, datetime, timedelta, timezone  # 날짜·시각·시차

# shortcut: 모든 회사를 서울 시간(UTC+9, 서머타임 없음)으로 본다. 다른 시간대 회사를 받으면 회사별 시간대 칸을 둔다
SEOUL = timezone(timedelta(hours=9))  # 한국 표준시


def seoul_today() -> date:
    """서울 기준 오늘. DB 서버(UTC)의 CURRENT_DATE 는 새벽 0~9시에 하루 늦으므로 쓰지 않는다."""
    return datetime.now(SEOUL).date()  # 예) UTC 11-03 16:00 = 서울 11-04 01:00 → 11-04


MIN_HISTORY_YEARS = 5  # 입출고일 하한: 오늘로부터 5년 전까지만 받는다 (#190). 0202-11-01 같은 오타가 "첫 입출고일"이 되면 추천의 14일 판정이 깨진다


def oldest_allowed(today: date) -> date:
    """받을 수 있는 가장 이른 입출고일. 예) 2026-11-12 → 2021-11-12 (이 날은 통과, 하루 전은 막힘)."""
    try:
        return today.replace(year=today.year - MIN_HISTORY_YEARS)
    except ValueError:  # 2/29 → 5년 전엔 2/29 가 없으면 2/28
        return today.replace(year=today.year - MIN_HISTORY_YEARS, day=28)


def date_problem(day: date, today: date) -> str | None:
    """입출고일 공통 검사 (직접 입출고·발주 입고·판매/입고 가져오기). 미래면 FUTURE_DATE, 5년보다 이르면 TOO_OLD_DATE, 괜찮으면 None."""
    if day > today:
        return "FUTURE_DATE"  # 아직 일어나지 않은 입출고가 재고·추천에 섞이지 않게
    if day < oldest_allowed(today):
        return "TOO_OLD_DATE"
    return None
