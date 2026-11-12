"""#193 가림 함수 단위 테스트 (DB·LLM 없음). LLM 에 가는 글자가 실제 값을 담지 않는지 확인한다."""

import pytest  # 테스트 도구

from app.services.import_mapping import MAX_COLUMNS, clean_header, llm_payload, shape


@pytest.mark.parametrize(("value", "expected"), [
    ("홍길동", "가가가"),  # 한글
    ("ㄱㄴ", "가가"),  # 한글 자모
    ("AbC", "AaA"),  # 영문 대소문자
    ("12345", "99999"),  # 숫자
    ("010-1234-5678", "999-9999-9999"),  # 전화번호는 모양만
    ("kim@shop.com", "aaa@aaaa.aaa"),  # 이메일도 모양만
    ("2026-11-01", "9999-99-99"),  # 날짜
    ("서울시 강남구 1-2", "가가가 가가가 9-9"),  # 주소
    ("12,000", "99,999"),  # 쉼표 금액
    ("漢字", "??"),  # 한자
    ("😀ok", "?aa"),  # 이모지
    ("탭\t줄\n", "가?가?"),  # 탭·줄바꿈은 ?
    ("", ""),  # 빈 값
])
def test_shape(value, expected):
    assert shape(value) == expected


def test_shape_long_text_is_cut():
    """20자를 넘으면 20자 모양 + … (원래 길이를 그대로 드러내지 않는다)."""
    assert shape("가" * 50) == "가" * 20 + "…"
    assert shape("A" * 20) == "A" * 20  # 딱 20자는 그대로


def test_shape_never_contains_original_letters():
    """한글·영문·숫자는 9·가·A·a 로만 남는다."""
    out = shape("ACME상사 Tel 02-555-0199")
    assert set(out) <= set("9가Aa -?…")
    assert "ACME" not in out and "상사" not in out and "555" not in out


@pytest.mark.parametrize(("header", "expected"), [
    ("상품코드", "상품코드"),  # 보통 머리글은 그대로
    ("  수량  ", "수량"),  # 앞뒤 공백 정리
    ("주문\n번호", "주문 번호"),  # 줄바꿈 → 공백
    ("상태\r\n\t(배송)", "상태 (배송)"),  # 여러 제어문자 → 공백 하나
    ("a\u202eb\u200bc\x00d", "a b c d"),  # 방향 바꿈·폭 없는 공백·NUL 제거
    ("가" * 60, "가" * 40),  # 40자로 자름
    ("2026-11-01", "9999-99-99"),  # 값처럼 보이는 머리글(날짜)은 모양으로
    ("12000", "99999"),  # 숫자 머리글도 모양으로
    ("A-001", "A-999"),  # 글자 5개 중 숫자 3개(절반 이상) → 코드 값으로 보고 가림
    ("2026년도 판매량", "2026년도 판매량"),  # 글자 9개 중 숫자 4개(절반 미만) → 머리글로 본다
    ("", ""),  # 빈 머리글
])
def test_clean_header(header, expected):
    assert clean_header(header) == expected


def test_payload_sends_only_shapes_three_per_column_from_first_five_rows():
    headers = ["상품명", "수량"]
    rows = [["사과", "1"], ["사과", "2"], ["배나무", "33"], ["귤", "444"], ["포도", "5"], ["마지막행비밀", "6"]]
    payload = llm_payload(headers, rows)
    assert payload == {"columns": [
        {"index": 0, "header": "상품명", "samples": ["가가", "가가가", "가"]},  # 겹치는 모양은 한 번, 최대 3개
        {"index": 1, "header": "수량", "samples": ["9", "99", "999"]},
    ]}
    text = str(payload)
    assert "사과" not in text and "마지막행비밀" not in text  # 실제 값은 없다


def test_payload_handles_short_rows_and_empty_cells():
    payload = llm_payload(["가", "나"], [["x"], ["", ""]])
    assert payload["columns"][1]["samples"] == []  # 칸이 모자라거나 비면 건너뛴다
    assert MAX_COLUMNS == 60
