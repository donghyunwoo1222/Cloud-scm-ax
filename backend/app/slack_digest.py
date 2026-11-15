"""아침 발주 추천 DM 을 한 번 보내고 끝나는 명령 (#197 PR 4). 같은 날 여러 번 실행해도 사람마다 한 통만 간다.

실행(저장소 맨 위 폴더):  docker compose exec backend python -m app.slack_digest
배포(#43): 플랫폼 예약 실행이 매일 서울 9시(UTC 0시)에 같은 명령을 부른다. 시각은 그 예약에만 있다.
종료 코드: 0 = 끝(보낼 것 없음·꺼짐 포함), 1 = 한 명 이상 실패(다시 실행하면 실패한 사람에게만 간다).
"""

import logging  # 사유 코드 한 줄

from app.clock import seoul_today  # 서울 기준 오늘
from app.services import slack_digest  # 실제 일


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)  # DEBUG 로그에 토큰이 섞일 수 있다
    counts = slack_digest.send_digests(seoul_today())
    logging.getLogger(__name__).info("slack_digest done %s", " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("SEND_FAILED") or counts.get("ERROR") else 0


if __name__ == "__main__":
    raise SystemExit(main())
