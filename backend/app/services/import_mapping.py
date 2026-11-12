"""가져오기 열 매핑 제안 (#193). LLM 이 "파일 열 → 가져오기 칸" 짝을 제안하고, 사용자가 화면에서 확인해야만 쓰인다.

LLM 에는 머리글(정리·40자)과 값의 "모양"(숫자→9, 한글→가, 영문→A/a)만 보낸다. 실제 값은 보내지 않는다(무료 키 규칙, #180).
LLM 답은 믿지 않는다: 스키마(래퍼) → 아는 칸인지 → 열이 파일에 있는지 → 중복 없음 → 필수 칸 → 각 가져오기의 열 검사.
하나라도 어기거나 LLM 이 꺼짐·실패·한도 초과면 source "rules" 로 돌려주고, 화면은 기존 열 지정(inspect 의 suggested)을 쓴다.
inspect·preview·commit 은 바꾸지 않는다. 이 파일은 아무것도 저장하지 않고, 값을 로그에 남기지 않는다.
"""

import re  # 머리글의 제어문자 지우기
from dataclasses import dataclass  # 가져오기 종류별 설정 묶음
from typing import Literal  # 칸 이름·확신도를 정해진 값으로 제한

from pydantic import BaseModel, Field, ValidationError  # 옵션 모양 검사

from app.errors import AppError  # 각 가져오기의 열 검사가 내는 오류
from app.schemas.product_import import ProductImportOptions
from app.schemas.receipt_import import ReceiptImportOptions
from app.schemas.sales_import import SalesImportOptions
from app.services import (
    llm,  # LLM 은 이 래퍼로만 부른다
    product_import,
    receipt_import,
    sales_import,
)
from app.services.import_templates import PRODUCT_HEADERS, SALES_HEADERS  # 템플릿 머리글

MAX_COLUMNS = 60  # 이보다 열이 많으면 LLM 을 부르지 않는다 (입력이 커지고 비용·실수가 늘어난다)
HEADER_CHARS = 40  # 머리글은 40자까지만 보낸다
SHAPE_CHARS = 20  # 값 모양은 20자까지만 만든다
SAMPLE_ROWS = 5  # LLM 에 보낼 모양은 앞쪽 5행에서만 고른다
SHAPES_PER_COLUMN = 3  # 열마다 겹치지 않는 모양 최대 3개
BROWSER_SAMPLES = 5  # 화면 확인용 실제 값 (브라우저에만, LLM·로그에는 안 감)
BROWSER_SAMPLE_CHARS = 30  # 화면 확인용 값 길이 상한
KEEP = set(" -/.:@_,()#+")  # 모양에서 그대로 두는 기호 (날짜·코드·전화 모양을 알아보게)
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]")  # 줄바꿈·제어·방향 문자


def shape(text: str) -> str:
    """값을 "모양"으로 바꾼다. 예) "홍길동" → "가가가", "010-1234-5678" → "999-9999-9999", "Ab-12" → "Aa-99"."""
    out = []
    for ch in text[:SHAPE_CHARS]:
        if "0" <= ch <= "9":
            out.append("9")
        elif "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㆎ":  # 한글 음절·자모
            out.append("가")
        elif "A" <= ch <= "Z":
            out.append("A")
        elif "a" <= ch <= "z":
            out.append("a")
        elif ch in KEEP:
            out.append(ch)
        else:
            out.append("?")  # 한자·이모지·탭 등 그 밖의 글자는 모두 ?
    return "".join(out) + ("…" if len(text) > SHAPE_CHARS else "")


def clean_header(header: str) -> str:
    """보내기 전 머리글 정리: 제어문자를 지우고 공백을 하나로, 40자로 자른다. 값처럼 보이면(숫자가 절반 이상) 모양으로 바꾼다.

    예) "주문\\n번호" → "주문 번호", "2026-11-01" → "9999-99-99" (첫 줄이 머리글이 아니라 데이터인 파일 대비).
    """
    text = " ".join(CONTROL.sub(" ", header).split())[:HEADER_CHARS]
    letters = text.replace(" ", "")
    if letters and sum(ch.isdigit() for ch in letters) * 2 >= len(letters):
        return shape(text)
    return text


def llm_payload(headers: list[str], rows: list[list[str]]) -> dict:
    """LLM 에 보낼 데이터: 열 번호·정리한 머리글·앞쪽 5행의 겹치지 않는 값 모양 최대 3개."""
    columns = []
    for i, header in enumerate(headers):
        shapes: list[str] = []
        for row in rows[:SAMPLE_ROWS]:
            value = row[i].strip() if i < len(row) else ""
            if value and (s := shape(value)) not in shapes and len(shapes) < SHAPES_PER_COLUMN:
                shapes.append(s)
        columns.append({"index": i, "header": clean_header(header), "samples": shapes})
    return {"columns": columns}


@dataclass(frozen=True)
class Kind:
    """가져오기 한 종류의 설정."""

    purpose: str  # llm.PROMPTS 이름
    fields: tuple[str, ...]  # 칸 이름들 (= 각 서비스의 HINTS 키, inspect 의 suggested 와 같은 모양)
    options: type[BaseModel]  # 열 지정 옵션 모양
    check: object  # 각 서비스의 _check_columns (열 범위·겹침·조건 검사)
    hints: dict  # 규칙 기반 힌트 (템플릿 일치 때 그대로 쓴다)
    template: list[str] | None  # 템플릿 머리글 (없으면 None)
    schema: type[llm.LLMOutput]  # LLM 출력 모양

    @property
    def required(self) -> list[str]:
        return [f for f in self.fields if self.options.model_fields[f].is_required()]


def _schema(fields: tuple[str, ...]) -> type[llm.LLMOutput]:
    """칸 이름은 이 종류의 칸만, 확신도는 high|low 만 허용하는 출력 모양."""

    class Pick(llm.LLMOutput):
        field: Literal[fields]  # 고른 칸 이름 (이 종류의 칸만)
        column: int = Field(ge=0, strict=True)  # 파일 열 번호 (0부터). strict: "3" 같은 글자 숫자도 형식 위반
        confidence: Literal["high", "low"]  # 확신도 (low 는 화면에서 강조)

    class Mapping(llm.LLMOutput):
        picks: list[Pick] = Field(max_length=len(fields))

    return Mapping


def _kind(name, fields_help, options, service, template) -> Kind:
    fields = tuple(service.HINTS)
    lines = "\n".join(f"- {f}: {fields_help[f]}" for f in fields)
    llm.PROMPTS[f"import_mapping_{name}"] = (  # 지시문(우리 글)은 system 칸에만 들어간다
        "너는 업무 파일의 열을 재고 관리 프로그램의 가져오기 칸에 짝짓는다.\n"
        "데이터의 columns 는 열 번호(index)·머리글(header)·값 모양(samples)이다. 값 모양에서 9 는 숫자, 가 는 한글, "
        "A 는 영문 대문자, a 는 영문 소문자, ? 는 그 밖의 글자다.\n"
        f"칸 목록:\n{lines}\n"
        "각 칸에 맞는 열 번호를 picks 에 담아라. 맞는 열이 없거나 확신이 없으면 그 칸은 빼라. "
        "한 열은 한 칸에만 쓴다. 확신이 낮으면 confidence 를 low 로 하라."
    )
    return Kind(f"import_mapping_{name}", fields, options, service._check_columns, service.HINTS, template,
                _schema(fields))


KINDS = {
    "sales": _kind("sales", {
        "product_col": "상품 코드(SKU). 필수", "quantity_col": "판매 수량(정수). 필수",
        "date_col": "판매·발송 날짜. 필수", "ref_col": "주문마다 다른 고유 주문번호. 필수",
        "status_col": "주문 상태(배송완료 등). 선택", "option_col": "상품 옵션(색상·사이즈 글자). 선택",
    }, SalesImportOptions, sales_import, SALES_HEADERS),
    "receipts": _kind("receipts", {
        "product_col": "상품 코드(SKU). 필수", "quantity_col": "입고 수량(정수). 선택",
        "date_col": "입고 날짜. 수량이 있으면 필수", "ref_col": "입고·전표 고유 번호. 선택",
        "name_col": "품목명. 선택", "unit_col": "단위(EA·개 등). 선택", "cost_col": "매입 단가(원). 선택",
        "safety_col": "안전재고(정수). 선택", "supplier_col": "공급업체·거래처 이름. 선택",
    }, ReceiptImportOptions, receipt_import, None),
    "products": _kind("products", {
        "product_col": "SKU. 필수", "name_col": "품목명. 필수", "unit_col": "기본·재고 단위(EA 등). 필수",
        "cost_col": "구매 단가(원). 필수", "safety_col": "안전재고(정수). 선택",
        "order_unit_col": "발주단위 이름(BOX 등). 선택", "factor_col": "환산계수(발주단위 1개당 재고 단위 수). 선택",
        "box_cost_col": "발주단위 단가(원). 선택", "moq_col": "최소 주문량(발주단위 수). 선택",
        "color_col": "색상. 선택", "size_col": "사이즈. 선택", "spec_col": "규격. 선택", "group_col": "그룹 코드. 선택",
    }, ProductImportOptions, product_import, PRODUCT_HEADERS),
}


def _checked(kind: Kind, headers: list[str], answer) -> tuple[dict, dict] | None:
    """LLM 답을 서버 규칙으로 검사한다. 통과하면 (칸→열, 칸→확신도), 하나라도 어기면 None (답 전체를 버린다)."""
    mapping: dict[str, int | None] = dict.fromkeys(kind.fields)
    confidence: dict[str, str] = {}
    for pick in answer.picks:
        if pick.column >= len(headers):  # 없는 열
            return None
        if mapping[pick.field] is not None:  # 같은 칸을 두 번
            return None
        mapping[pick.field], confidence[pick.field] = pick.column, pick.confidence
    chosen = [c for c in mapping.values() if c is not None]
    if len(set(chosen)) != len(chosen):  # 한 열을 두 칸에
        return None
    if any(mapping[f] is None for f in kind.required):  # 필수 칸 누락
        return None
    try:
        kind.check(headers, kind.options(**{f: c for f, c in mapping.items() if c is not None}))  # 각 가져오기의 열 규칙
    except (ValidationError, AppError):
        return None
    return mapping, confidence


def _samples(mapping: dict, rows: list[list[str]]) -> dict[str, list[str]]:
    """화면 확인용: 짝지어진 칸만, 비어 있지 않은 앞쪽 값 5개(30자까지). 브라우저에만 돌려주고 LLM·로그에는 쓰지 않는다."""
    out = {}
    for field, col in mapping.items():
        if col is None:
            continue
        values = [row[col].strip()[:BROWSER_SAMPLE_CHARS] for row in rows if col < len(row) and row[col].strip()]
        out[field] = values[:BROWSER_SAMPLES]
    return out


def _rules(reason: str) -> dict:
    return {"source": "rules", "reason": reason, "mapping": None, "confidence": None, "samples": None}


def suggest(company_id: int, kind_name: str, filename: str, content: bytes) -> dict:
    """열 매핑 제안. company_id 는 로그인 토큰의 회사(호출 API 가 user.company_id 만 넘긴다).

    응답 source: "template"(템플릿과 머리글이 같아 LLM 을 부르지 않음), "llm"(검증 통과), "rules"(그 밖, 기존 열 지정 화면).
    reason 은 코드 값만 담는다(래퍼의 DISABLED·DAILY_LIMIT·TIMEOUT 등, 또는 TOO_MANY_COLUMNS·INVALID_MAPPING).
    파일을 읽을 수 없으면 inspect 와 같은 422 를 낸다.
    """
    kind = KINDS[kind_name]
    headers, rows = sales_import.read_table(filename, content)  # 크기·형식 검사는 inspect 와 같다
    if kind.template is not None and headers == kind.template:
        mapping = sales_import.suggest_columns(headers, kind.hints)  # 템플릿이면 규칙 힌트가 정확하다
        return {"source": "template", "reason": None, "mapping": mapping,
                "confidence": {f: "high" for f, c in mapping.items() if c is not None}, "samples": _samples(mapping, rows)}
    if len(headers) > MAX_COLUMNS:
        return _rules("TOO_MANY_COLUMNS")
    try:
        answer = llm.ask(company_id, kind.purpose, llm_payload(headers, rows), kind.schema)
    except llm.LLMUnavailable as exc:
        return _rules(exc.reason)  # 꺼짐·한도·장애·시간 초과·형식 오류: 조용히 기존 화면으로
    checked = _checked(kind, headers, answer)
    if checked is None:
        return _rules("INVALID_MAPPING")
    mapping, confidence = checked
    return {"source": "llm", "reason": None, "mapping": mapping, "confidence": confidence,
            "samples": _samples(mapping, rows)}
