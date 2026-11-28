"""가져오기 숫자 칸(단가·안전재고 등)의 쉼표 규칙: 수량과 같이 올바른 천 단위만 허용."""

import pytest  # 테스트 도구

from app.services.receipt_import import _int_or_text
from tests.helpers import login_as
from tests.test_receipt_import import csv_file, day, post


@pytest.mark.parametrize("text,expected", [("1234", 1234), ("1,234", 1234), ("12,345", 12345), ("1,234,567", 1234567),
                                           ("1,5", "1,5"), ("12,34", "12,34"), ("1,2345", "1,2345"), ("1.5", "1.5"), ("", "")])
def test_int_or_text(text, expected):
    assert _int_or_text(text) == expected  # 틀린 쉼표는 글자 그대로 남아 검사에서 걸린다


def test_receipt_import_cost_comma(client, world):
    """단가 "1,5" → 문제 행(반영 안 함), "1,234" → 통과."""
    login_as(client)
    content = csv_file(f"{day(1)},NEW-A,새A,개,\"1,234\",3,", f"{day(1)},NEW-B,새B,개,\"1,5\",3,")
    preview = post(client, "/preview", content, world).json()["data"]
    assert (preview["new_product_count"], preview["problem_count"]) == (1, 1)
    assert [p["row"] for p in preview["problems"]] == [3] and preview["new_products"][0]["unit_cost"] == 1234
