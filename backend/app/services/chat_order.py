"""채팅으로 발주 초안 만들기 (#197 PR 5a). 채널 중립 서비스 계층: 슬랙을 모르고 글자·품목 목록·확인 토큰 문자열만 주고받는다.

흐름: propose(말 → 요약 + 확인 토큰) → confirm(토큰 → 초안 생성) 또는 cancel(토큰 → 취소).
  propose  : 오늘의 추천 목록(웹 추천 화면과 같은 계산)에 번호를 붙여 LLM 에게 "어느 번호를 몇 개" 로만 해석시킨다.
             LLM 의 제안은 서버가 모두 다시 검사한다(없는 번호·중복·0·음수·환산 나머지·상한·이미 초안). LLM 자유 글은 사용자에게 보이지 않는다.
  confirm  : 서명(HMAC)·사람·날짜·만료 확인 → 멱등 키(nonce) 잡기 → create_drafts(잠금·서버 재계산)를 같은 트랜잭션에서.
  cancel   : 같은 nonce 를 잡아 취소 뒤에는 확인이 안 되게 한다.
이 파일은 초안(DRAFT)만 만든다. 승인·발주는 웹에서 한다(승인은 관리자만).
권한: 웹 POST /recommendations/drafts 와 같다 — 활성 사용자, ADMIN·STAFF 모두, 임시 비밀번호를 바꾸기 전에는 불가. 더 넓게 열지 않는다.
LLM 에는 번호·품목명·색상·사이즈·규격·SKU·발주단위·환산계수·추천 수량과 사용자가 쓴 글만 보낸다(단가·공급업체·재고·사용자 이름·이메일 없음).
로그: 사유 코드·건수·번호만. 토큰·원문·슬랙 id 는 남기지 않는다.
돌려주는 글은 일반 글자다. 슬랙에 보낼 때 & < > 바꾸기는 어댑터가 한다.
"""

import base64  # 토큰을 글자로
import hashlib  # SHA-256
import hmac  # 서명
import json  # 토큰 내용
import logging  # 사유 코드 한 줄
import secrets  # 요청마다 다른 nonce
from collections import Counter  # 같은 번호가 두 번 나왔는지 세기
from dataclasses import dataclass, field  # 돌려주는 값 묶음
from datetime import date, datetime, timedelta  # 날짜·시각
from typing import Literal  # 정해진 글자만

from pydantic import Field, StrictInt  # LLM 출력 칸 검사
from sqlalchemy import select  # 조회
from sqlalchemy.orm import Session  # DB 세션

from app.config import settings  # SECRET_KEY
from app.errors import AppError  # create_drafts 가 내는 오류
from app.models import Product, PurchaseOrderItem, SlackLink, User  # 표
from app.schemas.common import MAX_QUANTITY  # 환산 후 수량 상한
from app.schemas.recommendations import DraftCreate, DraftItemIn  # create_drafts 입력
from app.services import idempotency, llm  # 중복 막기, LLM 공통 래퍼
from app.services.products import product_label  # 품목 표시(옵션 포함, 아침 DM 과 같은 함수)
from app.services.recommendations import create_drafts, list_recommendations  # 웹과 같은 추천·초안

log = logging.getLogger(__name__)

ENDPOINT = "slack:confirm"  # idempotency_keys endpoint (웹 경로·slack:event·slack:digest 와 겹치지 않는 이름)
MAX_LINES = 20  # 한 번에 다루는 품목 수 (후보도, 초안 줄도 최대 20)
MULTIPLE = 3  # 수량 상한 = 추천 발주단위 수 × 3 (예: 추천 2박스 → 최대 6박스)
CONFIRM_MINUTES = 30  # 확인 만료
MAX_TEXT = 500  # LLM 에 보내는 사용자 글 최대 글자 수

MSG_UNAVAILABLE = "지금은 자동 처리가 안 돼요. 웹에서 처리해 주세요."
MSG_NOT_LINKED = "슬랙 연결이 필요해요. 웹의 슬랙 연결 화면에서 먼저 연결해 주세요."
MSG_NO_ITEMS = "지금 발주를 검토할 품목이 없어요."
MSG_NO_LINES = "어떤 품목을 몇 개 발주할지 알아듣지 못했어요. 예: '1번 3박스' 또는 '전부'."
MSG_INVALID = "확인 정보가 올바르지 않아요. 처음부터 다시 요청해 주세요."
MSG_WRONG_USER = "요청한 사람만 확인할 수 있어요."
MSG_EXPIRED = "확인 시간이 지났어요. 처음부터 다시 요청해 주세요."
MSG_DONE = "이미 처리된 요청이에요."
MSG_CHANGED = "품목 정보가 바뀌었어요. 처음부터 다시 요청해 주세요."
MSG_BLOCKED = "지금은 초안을 만들 수 없어요. 웹의 발주 추천 화면에서 확인해 주세요."
NOTE = {  # 건너뛴 줄의 사유 (LLM 글이 아니라 고정 문장)
    "UNKNOWN_NUMBER": "목록에 없는 번호예요",
    "DUPLICATE": "같은 번호가 여러 번 있어 건너뛰었어요",
    "BAD_QUANTITY": "수량이 올바르지 않아요",
    "NOT_DIVISIBLE": "발주단위로 나누어떨어지지 않아요",
    "TOO_MANY": "추천 수량의 3배를 넘어요",
    "ALREADY_DRAFT": "이미 작성 중 발주서에 있어요",
}


@dataclass
class Reply:
    """어댑터에 내주는 값. text 는 보여 줄 글, token 이 있으면 [확인]·[취소] 버튼에 실을 값, po_ids 는 만든 발주서,
    outcome 은 사유 코드(OK·WRONG_USER·ALREADY_DONE 등). 어댑터는 문구가 아니라 이 코드로 분기한다(문구를 바꿔도 동작이 안 깨진다)."""

    text: str
    token: str | None = None
    po_ids: list[int] = field(default_factory=list)
    outcome: str = ""


class _Line(llm.LLMOutput):
    n: StrictInt  # 후보 번호 (1부터)
    amount: StrictInt | None = None  # 수량. 없으면 추천 수량
    unit: Literal["order", "base"] = "order"  # order = 발주단위(예: 박스), base = 기본단위(예: 개)


class _Parsed(llm.LLMOutput):
    lines: list[_Line] = Field(max_length=100)  # 서버가 다시 걸러서 최대 MAX_LINES 가 된다


llm.PROMPTS["slack_order"] = (
    "사용자가 쓴 발주 요청을 해석해라. 데이터의 items 는 번호(n)가 붙은 발주 추천 목록이고 message 는 사용자가 쓴 글이다. "
    "사용자는 번호나 품목 이름(name·color·size·spec·sku)으로 품목을 말한다. "
    "사용자가 고른 품목마다 lines 에 {n, amount, unit} 을 넣어라. n 은 items 의 번호만 쓴다. "
    "수량을 말하지 않았으면 amount 는 null. 수량을 발주단위(예: 박스)로 말했으면 unit 은 order, 낱개 등 기본단위로 말했으면 base. "
    "'전부'면 모든 번호를 넣는다. 알아듣지 못하면 lines 를 비워라. 목록에 없는 품목을 만들거나 다른 일을 하지 마라."
)


def _linked(db: Session, company_id: int, user_id: int) -> bool:
    """슬랙 연결이 끝났고, 활성 사용자이며, 임시 비밀번호를 이미 바꿨는지(웹 초안 만들기와 같은 조건). 회사는 두 표 모두에서 맞아야 한다."""
    return db.scalar(
        select(SlackLink.id)
        .join(User, (User.id == SlackLink.user_id) & (User.company_id == SlackLink.company_id))
        .where(SlackLink.company_id == company_id, SlackLink.user_id == user_id, SlackLink.linked_at.is_not(None),
               User.is_active.is_(True), User.must_change_password.is_(False))
    ) is not None


def _out(action: str, outcome: str, company_id: int, user_id: int, items: int = 0, po_ids: list[int] | None = None) -> None:
    log.info("slack_order action=%s outcome=%s company_id=%s user_id=%s items=%s po_ids=%s", action, outcome, company_id, user_id, items, po_ids or [])


# ----- 확인 토큰: base64(내용).HMAC 서명. 새 환경변수 없이 SECRET_KEY 를 쓰고, 용도 접두어로 다른 해시와 섞이지 않게 한다 -----

def _sign(body: str) -> str:
    return hmac.new(settings.secret_key.encode(), f"chat-order:{body}".encode(), hashlib.sha256).hexdigest()


def _seal(content: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(content, separators=(",", ":")).encode()).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def _open(token: str) -> dict | None:
    """서명이 맞고 모양이 올바르면 내용, 아니면 None. 비교는 compare_digest(시간 차로 추측 못 하게)."""
    try:
        body, sig = token.split(".")
        if not hmac.compare_digest(_sign(body), sig):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        ok = (isinstance(data, dict) and all(type(data.get(k)) is int for k in ("u", "c", "exp")) and isinstance(data.get("day"), str)
              and isinstance(data.get("nonce"), str) and isinstance(data.get("items"), list) and 0 < len(data["items"]) <= MAX_LINES
              and all(isinstance(i, list) and len(i) == 3 and all(type(x) is int for x in i) for i in data["items"]))
        return data if ok else None
    except Exception:  # noqa: BLE001  깨진 글자는 모두 위조로 본다
        return None


def _aware(at: datetime) -> None:
    """시간대 없는 시각은 서버 지역 시각으로 잘못 읽혀 만료가 어긋난다. 호출한 쪽 실수이므로 바로 알린다."""
    if at.tzinfo is None:
        raise ValueError("at 은 시간대가 있는 시각이어야 합니다 (예: datetime.now(UTC))")


def _label(item: dict) -> str:
    """추천 항목(dict)의 품목 표시: '기본 티셔츠 · 검정 / M (TS-BK-M)'."""
    return product_label(item["product_name"], item["product_sku"], item["color"], item["size"], item["spec"])


def _shown(item: dict, units: int) -> str:
    """'3 박스(300개)' 또는 '160개'."""
    base = units * item["unit_factor"]
    return f"{units:,} {item['order_unit']}({base:,}{item['unit']})" if item["unit_factor"] > 1 else f"{base:,}{item['unit']}"


def _moq_warning(item: dict, units: int) -> str:
    """최소 주문량보다 적으면 안내만 붙인다(막지 않는다). 웹(#194)과 같은 기준: 발주단위 수 < 최소 주문량, 단위는 발주단위(박스 없으면 재고 단위)."""
    moq = item["min_order_units"]
    return f" ⚠ 최소 주문량 {moq:,}{item['order_unit']}보다 적어요" if moq is not None and units < moq else ""


def propose(db: Session, company_id: int, user_id: int, text: str, today: date, at: datetime) -> Reply:
    """사용자가 쓴 글 → 요약 글 + 확인 토큰. 아무것도 저장하지 않는다. company_id·user_id 는 슬랙 연결 행에서 온 값만 넘긴다."""
    _aware(at)
    if not _linked(db, company_id, user_id):
        _out("PROPOSE", "NOT_LINKED", company_id, user_id)
        return Reply(MSG_NOT_LINKED, outcome="NOT_LINKED")  # LLM 을 부르지 않는다
    items = list_recommendations(company_id, db, today)["items"]
    if not items:
        _out("PROPOSE", "NO_ITEMS", company_id, user_id)
        return Reply(MSG_NO_ITEMS, outcome="NO_ITEMS")  # LLM 을 부르지 않는다
    cands = items[:MAX_LINES]  # 번호 n = 위치 + 1 (웹 목록 순서)
    data = {"message": text[:MAX_TEXT], "items": [
        {"n": n, "name": c["product_name"], "color": c["color"], "size": c["size"], "spec": c["spec"],
         "sku": c["product_sku"], "order_unit": c["order_unit"], "unit_factor": c["unit_factor"],
         "recommended_units": c["recommended_order_units"]} for n, c in enumerate(cands, 1)]}
    db.rollback()  # 후보를 다 읽었다(읽기만 했다). LLM 을 기다리는 최대 20초 동안 DB 연결을 붙잡지 않게 돌려준다. 이 뒤로 db 를 쓰지 않는다
    try:
        parsed = llm.ask(company_id, "slack_order", data, _Parsed)
    except llm.LLMUnavailable as exc:  # 한도·꺼짐·시간 초과·응답 오류 모두 같은 한 문장
        _out("PROPOSE", f"LLM_{exc.reason}", company_id, user_id)
        return Reply(MSG_UNAVAILABLE, outcome=f"LLM_{exc.reason}")

    repeated = {n for n, count in Counter(line.n for line in parsed.lines).items() if count > 1}  # 같은 번호가 둘이면 어느 쪽인지 알 수 없다
    picked: list[tuple[dict, int]] = []  # (후보, 발주단위 수)
    def who(n: int) -> str:  # 어느 품목인지 알 수 있게 목록 안의 번호면 품목 표시를 붙인다
        return f" {_label(cands[n - 1])}" if 1 <= n <= len(cands) else ""

    notes = [f"{n}번{who(n)}: {NOTE['DUPLICATE']}" for n in sorted(repeated)]  # 번호마다 한 번만 알린다
    for line in parsed.lines:
        reason = None
        if line.n in repeated:
            continue
        if not 1 <= line.n <= len(cands):
            reason = "UNKNOWN_NUMBER"
        else:
            item = cands[line.n - 1]
            factor, rec = item["unit_factor"], item["recommended_order_units"]
            if item["draft"]:
                reason = "ALREADY_DRAFT"
            elif line.amount is None:
                units = rec
            elif line.amount <= 0:
                reason = "BAD_QUANTITY"
            elif line.unit == "base" and line.amount % factor:
                reason = "NOT_DIVISIBLE"  # 예: 250개, 1박스=100 → 나머지 50
            else:
                units = line.amount // factor if line.unit == "base" else line.amount
            if reason is None and (units > rec * MULTIPLE or units * factor > MAX_QUANTITY):
                reason = "TOO_MANY"
            if reason is None:
                picked.append((item, units))
        if reason:
            notes.append(f"{line.n}번{who(line.n)}: {NOTE[reason]}")
    if not picked:
        _out("PROPOSE", "NO_LINES", company_id, user_id)
        return Reply("\n".join([MSG_NO_LINES, *notes]), outcome="NO_LINES")

    token = _seal({"u": user_id, "c": company_id, "day": today.isoformat(), "exp": int((at + timedelta(minutes=CONFIRM_MINUTES)).timestamp()),
                   "nonce": secrets.token_urlsafe(12), "items": [[c["product_id"], units, c["unit_factor"]] for c, units in picked]})
    lines = ["이대로 발주 초안을 만들까요? (아직 만들지 않았어요)",
             *[f"• {_label(c)} — {_shown(c, units)}{_moq_warning(c, units)}" for c, units in picked], *notes]
    if len(items) > len(cands):
        lines.append(f"추천 {len(items):,}개 중 앞 {len(cands)}개만 다뤄요. 나머지는 웹에서 확인해 주세요.")
    _out("PROPOSE", "OK", company_id, user_id, len(picked))
    return Reply("\n".join(lines), token, outcome="OK")


def _check(db: Session, company_id: int, user_id: int, token: str, today: date | None, at: datetime | None, action: str) -> tuple[dict | None, Reply | None]:
    """confirm·cancel 공통 앞검사: 서명 → 같은 사람 → (확인만) 날짜·만료 → 아직 연결·활성. 통과하면 (내용, None), 아니면 (None, 안내)."""
    data = _open(token)
    if data is None:
        _out(action, "INVALID_TOKEN", company_id, user_id)
        return None, Reply(MSG_INVALID, outcome="INVALID_TOKEN")
    if (data["c"], data["u"]) != (company_id, user_id):  # 다른 사람이 눌렀다. nonce 는 건드리지 않는다
        _out(action, "WRONG_USER", company_id, user_id)
        return None, Reply(MSG_WRONG_USER, outcome="WRONG_USER")
    if today is not None and (data["day"] != today.isoformat() or at.timestamp() >= data["exp"]):  # 서울 날짜가 바뀌었거나 30분 지남
        _out(action, "EXPIRED", company_id, user_id)
        return None, Reply(MSG_EXPIRED, outcome="EXPIRED")
    if not _linked(db, company_id, user_id):  # 그사이 연결 해제·비활성
        _out(action, "NOT_LINKED", company_id, user_id)
        return None, Reply(MSG_NOT_LINKED, outcome="NOT_LINKED")
    return data, None


def confirm(db: Session, company_id: int, user_id: int, token: str, today: date, at: datetime) -> Reply:
    """[확인] 버튼: 토큰 속 품목으로 초안을 만든다. 성공은 commit, 막힌 경우(AppError·마스터 변경)는 rollback 후 안내 글을 돌려준다(멱등 키와 초안이 한 트랜잭션).
    그 밖의 예외도 rollback 한 뒤 그대로 다시 올려, 키와 반쪽 발주서가 세션에 남지 않는다."""
    _aware(at)
    data, early = _check(db, company_id, user_id, token, today, at, "CONFIRM")
    if early:
        return early
    try:  # 키 잡기부터 commit 까지 어떤 예외가 나도 rollback 한다(키와 반쪽 발주서가 세션에 남지 않게)
        if not idempotency.claim(db, company_id, ENDPOINT, data["nonce"]):  # 같은 토큰 두 번째 클릭, 또는 취소한 뒤
            db.rollback()
            _out("CONFIRM", "ALREADY_DONE", company_id, user_id)
            return Reply(MSG_DONE, outcome="ALREADY_DONE")
        lines = {pid: (units, factor) for pid, units, factor in data["items"]}
        prods = {p.id: p for p in db.scalars(select(Product).where(
            Product.company_id == company_id, Product.id.in_(lines)))}  # 회사 조건: 다른 회사 품목은 안 보인다
        boxes = {pid: p.units_per_box for pid, p in prods.items()}
        if set(boxes) != set(lines) or any((boxes[pid] or 1) != factor for pid, (_, factor) in lines.items()):
            raise _Changed
        results = create_drafts(company_id, db, user_id, today, DraftCreate(items=[  # created_by = 누른 사람. 잠금·추천 재계산은 여기서
            DraftItemIn(product_id=pid, box_quantity=units) if boxes[pid] is not None else DraftItemIn(product_id=pid, quantity=units)
            for pid, (units, _) in lines.items()]))
        orders = [order for order, _ in results]
        made = db.execute(select(PurchaseOrderItem).where(
            PurchaseOrderItem.company_id == company_id, PurchaseOrderItem.purchase_order_id.in_([o.id for o in orders]),
            PurchaseOrderItem.product_id.in_(lines)).order_by(PurchaseOrderItem.id)).scalars().all()
        if len(made) != len(lines) or any(m.quantity != lines[m.product_id][0] * lines[m.product_id][1] for m in made):  # 잠근 뒤 값이 승인한 수량과 같은지
            raise _Changed
        text = _made_text(orders, made, prods)  # 새로 만든 줄과 품목 마스터에서만 만든다(사용자 글·토큰 내용은 되풀이하지 않는다). commit 전에 만든다
        db.commit()
    except _Changed:
        db.rollback()  # 멱등 키도 취소
        _out("CONFIRM", "CHANGED", company_id, user_id, len(lines))
        return Reply(MSG_CHANGED, outcome="CHANGED")
    except AppError as exc:  # 더 이상 추천 대상이 아님·비활성·이미 초안 등
        db.rollback()
        _out("CONFIRM", f"BLOCKED_{exc.code}", company_id, user_id, len(lines))
        return Reply(MSG_BLOCKED, outcome=f"BLOCKED_{exc.code}")
    except Exception:
        db.rollback()  # 예상 못 한 오류: 되돌리고 부르는 쪽(어댑터)이 알 수 있게 그대로 올린다
        raise
    po_ids = [o.id for o in orders]
    _out("CONFIRM", "OK", company_id, user_id, len(lines), po_ids)
    return Reply(text, po_ids=po_ids, outcome="OK")


def _made_text(orders: list, made: list, prods: dict) -> str:
    """결과 문구: 발주서 번호별로 '• 품목 표시 — 수량'. 단가·공급업체·이메일은 넣지 않는다. 박스 품목은 요약과 같은 표기(3 박스(300개))."""
    out = ["발주 초안을 만들었어요. 승인된 발주가 아니라 초안이에요."]
    for order in orders:
        out.append(order.po_number)
        for m in made:
            if m.purchase_order_id != order.id:
                continue
            p = prods[m.product_id]
            factor = m.units_per_box or 1  # 발주 당시 입수 스냅샷(없으면 낱개)
            shown = _shown({"unit_factor": factor, "order_unit": m.order_unit, "unit": p.unit}, m.quantity // factor)
            out.append(f"• {product_label(p.name, p.sku, p.color, p.size, p.spec)} — {shown}")
    out.append("승인과 발주는 웹에서 해 주세요.")
    return "\n".join(out)


class _Changed(Exception):
    """승인한 내용과 지금 마스터가 달라졌다."""


def cancel(db: Session, company_id: int, user_id: int, token: str) -> Reply:
    """[취소] 버튼: 같은 nonce 를 잡아 이후 [확인]이 안 되게 한다. 이미 처리됐으면 안내만."""
    data, early = _check(db, company_id, user_id, token, None, None, "CANCEL")
    if early:
        return early
    try:
        if not idempotency.claim(db, company_id, ENDPOINT, data["nonce"]):
            db.rollback()
            _out("CANCEL", "ALREADY_DONE", company_id, user_id)
            return Reply(MSG_DONE, outcome="ALREADY_DONE")
        db.commit()
    except Exception:
        db.rollback()  # 예상 못 한 오류: 되돌리고 그대로 올린다
        raise
    _out("CANCEL", "OK", company_id, user_id)
    return Reply("취소했어요. 아무것도 만들지 않았어요.", outcome="OK")
