"""공급업체용 문서 누출 방지(#281): 문서 키 허용 목록 + 내부 전용 값이 문서·엑셀·PDF·메일 본문에 없는지. DB 없이 돈다.

분류표: docs/06-system-design/supplier-document-fields.md
build_document 의 DB 조회 함수(get_order·build_out·get_owned·user_names)를 가짜로 바꿔, 내부 전용 칸에 표식 글자를 넣은 발주서로 문서를 만든다.
"""

import json  # 문서 dict 전체를 글자 하나로
from datetime import UTC, datetime  # 작성·승인 시각
from io import BytesIO  # 엑셀 바이트 읽기
from types import SimpleNamespace  # 가짜 DB 행

import pytest  # 테스트 도구
from openpyxl import load_workbook  # 엑셀 읽기

from app.services import po_document as pd  # 대상 모듈
from app.services import po_mail  # 메일 본문
from tests.test_po_pdf import calls, render  # noqa: F401  PDF 글자 기록 장치 (같은 방식 재사용)

REASON = "SECRET-REASON-281"  # 추천 사유 (발주 줄)
CHANGE = "SECRET-CHANGELOG-281"  # 변경 이력 내용
EMAILED = "secret-emailed-281@internal.test"  # 메일 발송 이력 (emailed_to)
USER_EMAIL = "secret-user-281@internal.test"  # 작성자·승인자 로그인 이메일 (Reply-To 에만 쓰임)
CLOSED = "7654321"  # 잔량 마감 수량 표식 (다른 숫자와 겹치지 않는 값)
MEMO = "PUBLIC-MEMO-281"  # 메모는 공개 칸: 반드시 나가야 한다
SECRETS = (REASON, CHANGE, EMAILED, USER_EMAIL, CLOSED)
EMAIL_LOG = "secret-email-log-182@internal.test"  # 메일 발송 시도 이력(po_email_log)의 받는 주소·실패 코드 (#182)
SECRETS += (EMAIL_LOG,)
INTERNAL_IDS = ("987650001", "987650002", "987650003", "987650004", "987650005", "987650006", "987650007")  # 회사·발주서·사용자·업체·품목·줄 id 2개

# build_document 결과의 키 경로. 새 칸을 문서에 넣으면 이 테스트가 실패한다 → 분류표를 먼저 갱신하고 여기에 더한다
ALLOWED_KEYS = {
    "po_number", "status", "order_date",
    "supplier", "supplier.name", "supplier.contact_name", "supplier.phone", "supplier.email",
    "buyer", "buyer.name", "buyer.business_number", "buyer.representative", "buyer.phone", "buyer.address", "buyer.author_name",
    "lines", "lines[].no", "lines[].product_name", "lines[].product_sku", "lines[].unit", "lines[].quantity",
    "lines[].unit_price", "lines[].amount", "lines[].note",
    "supply_total", "vat", "total", "total_korean", "due_date", "delivery_address", "payment_terms", "memo",
    "approval", "approval.approver_name", "approval.approved_at", "approval.company_name",
    "approval.stamp", "approval.stamp.lines", "approval.stamp.ratio",
}


def key_paths(value, prefix=""):
    """중첩 dict·list 의 키 경로 집합. 예) {"a": [{"b": 1}]} → {"a", "a[].b"}."""
    if isinstance(value, list):
        return set().union(*(key_paths(item, prefix + "[]") for item in value)) if value else set()
    if not isinstance(value, dict):
        return set()
    paths = set()
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        paths |= {path} | key_paths(child, path)
    return paths


def item(item_id, name, boxed):
    """build_out 이 돌려주는 발주 줄 응답과 같은 칸 (내부 칸 포함)."""
    return {
        "id": int(item_id), "product_id": int(INTERNAL_IDS[4]), "product_sku": f"SKU-{name}", "product_name": name,
        "color": None, "size": None, "spec": None, "group_code": None, "unit": "개", "quantity": 20 if boxed else 7,
        "unit_price": 500, "recommended_quantity": 7, "units_per_box": 10 if boxed else None,
        "box_unit_price": 5000 if boxed else None, "box_quantity": 2 if boxed else None,
        "order_unit": "박스" if boxed else "개", "unit_factor": 10 if boxed else 1, "min_order_units": None,
        "line_total": 10000 if boxed else 3500, "recommendation_reason": REASON, "received_quantity": 0,
        "closed_quantity": int(CLOSED),  # 잔량 마감 수량 (#252): 내부 전용, 공급업체 문서에 새면 안 된다
    }


@pytest.fixture
def doc(monkeypatch):
    """내부 전용 칸마다 표식을 넣은 발주서로 build_document 를 돌린 결과."""
    company_id, order_id, user_id, supplier_id = (int(x) for x in INTERNAL_IDS[:4])
    now = datetime(2026, 11, 18, 0, 30, tzinfo=UTC)
    order = SimpleNamespace(
        id=order_id, company_id=company_id, po_number="PO-20261118-009", status="ORDERED", created_at=now,
        supplier_id=supplier_id, created_by=user_id, approved_by=user_id, approved_at=now, approved_company_name=None,
        due_date=None, delivery_address=None, payment_terms="월말", memo=MEMO,
        emailed_at=now, emailed_to=EMAILED, emailed_by=user_id,
    )
    company = SimpleNamespace(id=company_id, name="한빛생활", business_number="1234567890", representative="홍길동",
                              phone="02-1", address="서울시 1")
    supplier = SimpleNamespace(id=supplier_id, name="대한물산", contact_name="김대한", phone="02-2", email="sales@supplier.test")
    user = SimpleNamespace(id=user_id, company_id=company_id, name="이수진", email=USER_EMAIL)
    change_row = SimpleNamespace(field="memo", old_value=CHANGE, new_value=CHANGE, reason=CHANGE)  # 혹시 이력을 읽어도 표식이 나오게
    change_row.to_address = change_row.failure_code = EMAIL_LOG  # 메일 발송 이력 행으로 읽혀도 표식이 나오게 (#182)
    db = SimpleNamespace(get_one=lambda model, key: company, execute=lambda *a, **k: [change_row],
                         scalars=lambda *a, **k: [change_row])
    out = {"items": [item(INTERNAL_IDS[5], "물티슈", False), item(INTERNAL_IDS[6], "세제", True)]}
    monkeypatch.setattr(pd.po_service, "get_order", lambda *a: order)
    monkeypatch.setattr(pd.po_service, "build_out", lambda *a, **k: [out])
    monkeypatch.setattr(pd, "get_owned", lambda cid, _db, model, key: {pd.Supplier: supplier, pd.User: user}[model])
    monkeypatch.setattr(pd, "user_names", lambda cid, _db, ids: {user_id: user.name})
    return pd.build_document(company_id, db, order_id)


def xlsx_texts(data: bytes) -> list[str]:
    """엑셀의 모든 시트(숨김 포함)의 모든 칸 글자 + 시트 이름 + 문서 속성."""
    wb = load_workbook(BytesIO(data))
    texts = [repr(wb.properties)]
    for ws in wb.worksheets:
        texts.append(ws.title)
        texts += [str(cell.value) for row in ws.iter_rows() for cell in row if cell.value is not None]
    return texts


def outputs(doc, calls):  # noqa: F811
    """공급업체에게 가는 출력별 글자: 문서 JSON, 엑셀, PDF, 메일 제목·앞머리·HTML·글자 본문."""
    _, drawn = render(doc, calls)
    return {
        "json": json.dumps(doc, ensure_ascii=False),
        "xlsx": "\n".join(xlsx_texts(pd.build_xlsx(doc))),
        "pdf": "\n".join(c[4] for c in drawn),
        "mail": "\n".join((po_mail.subject_of(doc), po_mail.default_intro(doc), po_mail.fixed_html(doc), po_mail.fixed_text(doc))),
    }


def test_document_keys_match_allowlist(doc):
    extra, missing = key_paths(doc) - ALLOWED_KEYS, ALLOWED_KEYS - key_paths(doc)
    assert not extra and not missing, (
        f"문서 칸이 바뀌었습니다 (새 칸 {sorted(extra)}, 빠진 칸 {sorted(missing)}). "
        "docs의 분류표도 같이 갱신하세요: docs/06-system-design/supplier-document-fields.md"
    )


def test_internal_values_never_reach_supplier_outputs(doc, calls):  # noqa: F811
    for name, text in outputs(doc, calls).items():
        for secret in SECRETS + INTERNAL_IDS:
            assert secret not in text, f"내부 전용 값 {secret!r} 이 {name} 출력에 들어갔습니다"


def test_memo_is_intentionally_public(doc, calls):  # noqa: F811
    # 메모("4) 기타")는 공급업체에 전달되는 칸이다(#281 결정). 화면 라벨도 그렇게 안내한다
    for name, text in outputs(doc, calls).items():
        assert MEMO in text, f"공개 칸 memo 가 {name} 출력에서 빠졌습니다"


def test_xlsx_author_property_is_empty(doc):
    # 엑셀 파일 속성의 작성자 기본값 "openpyxl" 이 남지 않는다 (PDF 속성이 빈 것과 같은 정책)
    assert not load_workbook(BytesIO(pd.build_xlsx(doc))).properties.creator
