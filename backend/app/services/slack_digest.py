"""아침 발주 추천 슬랙 DM (#197 PR 4). 연결된 사용자에게 오늘의 추천을 하루 한 번 보낸다. 읽기와 알림만 하고 초안·발주는 만들지 않는다.

실행은 app/slack_digest.py(한 번 돌고 끝나는 명령)를 바깥 cron 이 매일 부른다. 시각은 cron 줄에만 있다(새 설정 없음).
회사 분리: company_id 는 slack_links 행에서만 가져온다. 추천은 회사마다 한 번 계산(저장하지 않음)해 그 회사 사람들에게 보낸다.
중복 막기: 사람마다 idempotency_keys(endpoint "slack:digest", 키 "날짜:user_id")를 잡는다.
  순서는 키 잡기(미확정) → 슬랙 보내기 → 성공하면 확정, 실패하면 취소. 실패한 사람만 다시 실행 때 받는다.
  한 사람 = 세션·트랜잭션 하나라서 키를 잡고 있는 시간은 슬랙 호출 한 번(클라이언트 타임아웃 5초)뿐이다.
  shortcut: 보낸 뒤 확정 직전에 프로세스가 죽으면 다음 실행에서 한 번 더 간다(안 가는 것보다 낫다고 판단). 정확히 한 번이 필요해지면 슬랙 쪽 중복 확인을 더한다.
로그: 사유 코드와 회사·사용자 번호만. 토큰·슬랙 사용자 id·메시지 원문은 남기지 않는다.
"""

import logging  # 사유 코드 한 줄
from datetime import date  # 오늘 날짜 (인자로 받아 테스트가 고정한다)

from slack_sdk.errors import SlackApiError  # 슬랙이 거절한 응답 (error 코드만 남긴다)
from sqlalchemy import select  # 대상 조회

from app.config import settings  # SLACK_TEAM_ID·APP_BASE_URL
from app.db import (  # 추천 읽기(한 시점)·키 잡기 전용 세션 (테스트는 바꿔 끼운다)
    ReadSessionLocal,
    SessionLocal,
)
from app.models import SlackLink, User  # 슬랙 연결, 사용자(활성 여부)
from app.services import idempotency, slack_client, slack_link  # 중복 막기, 보내기, 켜짐 여부
from app.services.products import product_label  # 품목 표시(옵션 포함)
from app.services.recommendations import list_recommendations  # 웹 추천 화면과 같은 계산

log = logging.getLogger(__name__)

ENDPOINT = "slack:digest"  # idempotency_keys 의 endpoint 칸 (웹 경로·slack:event 와 겹치지 않는 이름)
MAX_LINES = 10  # 메시지에 넣는 최대 품목 수. 넘치면 "외 N개"로 웹에 안내
WEB_PATH = "/recommendations"  # 웹 추천 화면 (frontend/app/(app)/recommendations, (app) 은 주소에 안 붙는 묶음)
NO_LINK = "웹의 '발주 추천' 화면"
REPLY_HINT = "답장 예: 1번 3박스"  # 이 DM 에 답장하면 발주 초안 요약이 온다(#197 PR 5b)


def _escape(value: str) -> str:
    """슬랙 글에서 & < > 는 특수 문자라 바꿔 보낸다 (예: '<A&B>' → '&lt;A&amp;B&gt;')."""
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _quantity(item: dict) -> str:
    """발주단위가 따로 있으면 '3 BOX(300개)', 없으면 '160개'."""
    unit, arrival = item["unit"], item["recommended_arrival_quantity"]
    if item["unit_factor"] > 1:
        return f"{item['recommended_order_units']:,} {_escape(item['order_unit'])}({arrival:,}{_escape(unit)})"
    return f"{arrival:,}{_escape(unit)}"  # 환산 1이면 발주단위 수 = 도착 수량 (최소 주문량 반영)


def _line(n: int, item: dict) -> str:  # n: 줄 번호(1부터). 답장의 "1번"이 가리키는 번호와 같은 순서다
    label = product_label(item["product_name"], item["product_sku"], item["color"], item["size"], item["spec"])  # 옵션 포함 공용 표시
    text = (f"{n}. {_escape(label)} — {_quantity(item)} 추천"
            f" · 지금 쓸 수 있는 재고 {item['available']:,}{_escape(item['unit'])}")
    if item["draft"]:  # 아직 주문 전이라 추천에 남는다. 이미 담았다는 것만 알린다
        text += f" · 작성 중 발주서 {_escape(item['draft']['po_number'])}에 있어요"
    return text


def build_message(items: list[dict], day: date, base_url: str) -> str:
    """추천 목록(웹 추천 API 의 items 모양)으로 DM 글을 만든다. DB·슬랙을 쓰지 않는 순수 함수."""
    url = base_url.rstrip("/") + WEB_PATH if base_url.startswith("https://") else None  # https 주소일 때만 링크
    lines = [f"☀️ 오늘의 발주 추천 ({day.month}월 {day.day}일)", f"발주를 검토할 품목이 {len(items):,}개 있어요.", ""]
    lines += [_line(n, item) for n, item in enumerate(items[:MAX_LINES], 1)]  # 웹 목록 순서(최신 품목 먼저) 그대로
    rest = len(items) - MAX_LINES
    if rest > 0:
        lines.append(f"외 {rest:,}개는 웹에서 확인해 주세요: {url}" if url else f"외 {rest:,}개는 {NO_LINK}에서 확인해 주세요.")
    else:
        lines.append(f"자세한 이유: {url}" if url else f"자세한 이유는 {NO_LINK}에서 볼 수 있어요.")
    lines.append(REPLY_HINT)  # 번호는 답장하는 시점의 목록 기준이라, 만들기 전에 요약에서 품목 이름을 다시 확인한다
    return "\n".join(lines)


def _targets() -> dict[int, list[tuple[int, str]]]:
    """회사 id → [(사용자 id, 슬랙 사용자 id)]. 연결 완료 + 허용한 워크스페이스 + 활성 사용자만. 회사는 slack_links 행에서."""
    with SessionLocal() as db:
        rows = db.execute(
            select(SlackLink.company_id, SlackLink.user_id, SlackLink.slack_user_id)
            .join(User, (User.id == SlackLink.user_id) & (User.company_id == SlackLink.company_id))  # 같은 회사 사용자만 (방어)
            .where(SlackLink.slack_user_id.is_not(None), SlackLink.slack_team_id == settings.slack_team_id,
                   User.is_active.is_(True))
            .order_by(SlackLink.company_id, SlackLink.user_id)
        ).all()
        db.rollback()  # 읽기만 했다
    out: dict[int, list[tuple[int, str]]] = {}
    for company_id, user_id, slack_user_id in rows:
        out.setdefault(company_id, []).append((user_id, slack_user_id))
    return out


def _outcome(code: str, company_id: int, user_id: int | None = None, items: int | None = None, error: str | None = None) -> None:
    log.info("slack_digest outcome=%s company_id=%s user_id=%s items=%s error=%s", code, company_id, user_id, items, error)


def _send_one(company_id: int, user_id: int, slack_user_id: str, text: str, day: date, count: int) -> str:
    """한 사람에게 한 통. 이 사람만의 세션·트랜잭션: 키 잡기 → 보내기 → 확정(실패면 취소). 사유 코드를 돌려준다."""
    with SessionLocal() as db:
        if not idempotency.claim(db, company_id, ENDPOINT, f"{day.isoformat()}:{user_id}"):  # 같은 날 이미 보냄 (동시 실행이면 앞의 확정을 기다린 뒤 False)
            db.rollback()
            _outcome("ALREADY_SENT", company_id, user_id)
            return "ALREADY_SENT"
        try:
            slack_client.get_client().post_message(slack_user_id, text)  # 사용자 id 를 채널로 주면 봇과의 DM 으로 간다. 타임아웃 5초(slack_client)
        except SlackApiError as exc:
            db.rollback()  # 키도 취소: 다시 실행하면 이 사람에게만 다시 보낸다
            _outcome("SEND_FAILED", company_id, user_id, error=exc.response.get("error"))
            return "SEND_FAILED"
        except Exception as exc:  # noqa: BLE001  연결 실패·시간 초과·토큰 없음 등. 다른 사람 발송은 계속한다
            db.rollback()
            _outcome("SEND_FAILED", company_id, user_id, error=type(exc).__name__)
            return "SEND_FAILED"
        db.commit()  # 보낸 뒤에만 키 확정
    _outcome("SENT", company_id, user_id, items=count)
    return "SENT"


def send_digests(today: date) -> dict[str, int]:
    """오늘의 추천을 연결된 사용자에게 보낸다. 사유 코드별 건수를 돌려준다. 어떤 회사·사람의 실패도 다른 쪽을 막지 않는다."""
    counts: dict[str, int] = {}
    if not slack_link.enabled():  # SLACK_ENABLED 꺼짐 또는 SLACK_TEAM_ID 비어 있음
        log.info("slack_digest disabled")
        return counts
    for company_id, people in _targets().items():  # 연결된 사람이 0명인 회사는 여기 없다 (계산도 안 한다)
        try:
            with ReadSessionLocal() as db:  # 웹 추천 화면과 같은 한 시점 읽기, 보내기 전에 닫는다
                items = list_recommendations(company_id, db, today)["items"]
                db.rollback()
        except Exception as exc:  # noqa: BLE001  이 회사 계산 실패는 이 회사만 건너뛴다
            _outcome("ERROR", company_id, error=type(exc).__name__)
            counts["ERROR"] = counts.get("ERROR", 0) + len(people)
            continue
        if not items:  # 추천 0개면 보내지 않는다
            _outcome("NO_ITEMS", company_id)
            counts["NO_ITEMS"] = counts.get("NO_ITEMS", 0) + len(people)
            continue
        text = build_message(items, today, settings.app_base_url)
        for user_id, slack_user_id in people:
            try:
                code = _send_one(company_id, user_id, slack_user_id, text, today, len(items))
            except Exception as exc:  # noqa: BLE001  키 잡기 중 DB 오류 등
                _outcome("ERROR", company_id, user_id, error=type(exc).__name__)
                code = "ERROR"
            counts[code] = counts.get(code, 0) + 1
    return counts
