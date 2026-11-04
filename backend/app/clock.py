"""오늘 날짜. 날짜 경계(입출고일 기본값, 최근 30일 등)는 회사 시간대 기준이다(api-design.md, 기본 Asia/Seoul)."""

from datetime import date, datetime, timedelta, timezone  # 날짜·시각·시차

# shortcut: 모든 회사를 서울 시간(UTC+9, 서머타임 없음)으로 본다. 다른 시간대 회사를 받으면 회사별 시간대 칸을 둔다
SEOUL = timezone(timedelta(hours=9))  # 한국 표준시


def seoul_today() -> date:
    """서울 기준 오늘. DB 서버(UTC)의 CURRENT_DATE 는 새벽 0~9시에 하루 늦으므로 쓰지 않는다."""
    return datetime.now(SEOUL).date()  # 예) UTC 11-03 16:00 = 서울 11-04 01:00 → 11-04
