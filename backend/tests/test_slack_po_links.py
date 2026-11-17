"""슬랙 [확인] 결과 글의 발주서 상세 주소(#249). 글 만들기는 _made_text 를 가짜 발주서로 직접 부르고, 실제 흐름 검사는 test_slack_order.py 맨 아래에 있다."""

import re  # 주소에 숫자 id 만 남았는지
from types import SimpleNamespace as NS  # 가짜 발주서·품목 줄

import pytest  # 테스트 도구

from app.config import settings  # APP_BASE_URL
from app.services import chat_order as co  # 검사 대상
from app.services import slack_events  # 글 → 슬랙 블록 나누기

BASE = "https://scm.example.com"
PROD = NS(name="상품", sku="S1", color=None, size=None, spec=None, unit="개")


def text_for(n: int) -> list[str]:
    """발주서 n장(각 품목 1줄)의 결과 글을 줄로 돌려준다."""
    made_orders = [NS(id=10 + i, po_number=f"PO-20261104-{i:03d}") for i in range(1, n + 1)]
    made = [NS(purchase_order_id=o.id, product_id=1, units_per_box=None, order_unit=None, quantity=3) for o in made_orders]
    return co._made_text(made_orders, made, {1: PROD}).split("\n")


def urls(lines: list[str]) -> list[str]:
    return [line for line in lines if "http" in line]


@pytest.fixture(autouse=True)
def https_base(monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", BASE)


@pytest.mark.parametrize("n", [1, 2, 5])
def test_one_url_per_order_up_to_five(n):
    lines = text_for(n)
    assert urls(lines) == [f"PO-20261104-{i:03d} {BASE}/purchase-orders/{10 + i}" for i in range(1, n + 1)]
    assert not any(line.startswith("외 ") for line in lines)


def test_six_or_more_shows_five_urls_and_rest_note():
    lines = text_for(8)
    assert len(urls(lines)) == 5 and "외 3건은 아래 웹 목록에서 확인해 주세요." in lines
    assert "PO-20261104-006" in lines  # 6번째부터는 번호만(주소 없음)


@pytest.mark.parametrize("base", ["", "http://localhost:3000", "javascript:alert(1)", "https://a.com/x|y", "https://a.com/<b>", "https://a.com/?a=1&b=2"])
def test_no_url_without_safe_https_base(monkeypatch, base):
    monkeypatch.setattr(settings, "app_base_url", base)
    lines = text_for(8)
    assert urls(lines) == [] and not any(line.startswith("외 ") for line in lines)  # 기존 글 그대로


@pytest.mark.parametrize("base", [BASE, BASE + "/", BASE + "//"])
def test_trailing_slash_does_not_double(monkeypatch, base):
    monkeypatch.setattr(settings, "app_base_url", base)
    assert urls(text_for(1)) == [f"PO-20261104-001 {BASE}/purchase-orders/11"]


def test_url_has_only_integer_id_and_no_extra_values():
    for line in urls(text_for(5)):
        assert re.fullmatch(r"PO-\d{8}-\d{3} https://scm\.example\.com/purchase-orders/\d+", line)  # 쿼리·토큰·회사·사용자 값이 없다


def test_long_result_with_urls_still_splits():
    lines = text_for(8)
    lines[1:1] = ["• " + "가" * 100] * 100  # 2,900자를 크게 넘는 긴 글
    blocks = slack_events._text_blocks("\n".join(lines))
    assert len(blocks) <= slack_events.MAX_BLOCKS and all(len(b["text"]["text"]) <= slack_events.BLOCK_TEXT_MAX for b in blocks)
