"""로그인 시도 제한(#168): 같은 이메일로 연속 실패가 쌓이면 잠시 로그인을 막는다.

키는 users 행이 아니라 입력한 이메일 글자다. 없는 이메일도 똑같이 세고 잠가서, 잠김 여부로 가입 여부를 알 수 없다.
shortcut: 서버 메모리에 둔다(재시작하면 초기화, 서버가 여러 대면 공유 안 됨). 서버를 늘리거나 재시작 초기화가 문제면 DB 표로 옮긴다(#43 배포 때 재검토).
"""

import threading  # 요청이 동시에 와도 횟수가 꼬이지 않게 하는 잠금
from datetime import UTC, datetime, timedelta  # 현재 시각, 시간 계산

from app.errors import AppError  # 공통 오류

MAX_FAILURES = 5  # 연속 실패 허용 횟수 (임시 확정, 인터뷰 후 재검토). 5번째 실패에서 잠근다
LOCK_MINUTES = 15  # 잠금 시간 (임시 확정). 마지막 실패 후 이만큼 지나면 횟수도 자동으로 잊는다
MAX_KEYS = 10000  # 메모리 보호: 이 개수를 넘으면 지난 기록부터 지운다
LOCKED_MESSAGE = "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요."  # 이메일이 있든 없든 같은 문장

_records: dict[str, tuple[int, datetime, datetime | None]] = {}  # 이메일 → (연속 실패 수, 마지막 실패 시각, 잠금 해제 시각)
_lock = threading.Lock()  # 딕셔너리를 한 번에 한 요청만 만지게 한다


def now() -> datetime:
    return datetime.now(UTC)  # 테스트가 이 함수를 바꿔 시간을 고정한다


def reset() -> None:
    with _lock:
        _records.clear()  # 모든 기록 삭제 (테스트용)


def check_not_locked(email: str, at: datetime) -> None:
    """잠금 중이면 429. 비밀번호가 맞아도 막는다."""
    with _lock:
        record = _records.get(email)  # 이 이메일의 기록 (없으면 None)
    if record and record[2] and record[2] > at:  # 잠금 해제 시각이 아직 안 지났으면
        raise AppError(429, "TOO_MANY_ATTEMPTS", LOCKED_MESSAGE)


def record_failure(email: str, at: datetime) -> None:
    """실패 1회 기록. 5번째면 15분 잠근다. 예) 12:00 실패 5번 → 12:15까지 잠금."""
    with _lock:
        count, last, _ = _records.get(email, (0, at, None))  # 이전 기록 (없으면 0회)
        if at - last >= timedelta(minutes=LOCK_MINUTES):  # 마지막 실패 후 15분이 지났으면 새로 센다
            count = 0
        count += 1  # 이번 실패
        locked_until = at + timedelta(minutes=LOCK_MINUTES) if count >= MAX_FAILURES else None  # 5번째면 잠금 시각
        _records[email] = (count, at, locked_until)
        if len(_records) > MAX_KEYS:  # 없는 이메일을 마구 보내 메모리를 채우는 공격 방어
            for key in sorted(_records, key=lambda k: _records[k][1])[: MAX_KEYS // 2]:  # 마지막 실패가 오래된 절반
                del _records[key]


def record_success(email: str) -> None:
    with _lock:
        _records.pop(email, None)  # 성공하면 연속 실패 횟수를 0으로 되돌린다
