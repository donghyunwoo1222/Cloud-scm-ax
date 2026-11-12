"""품목 마스터 가져오기(#189) 테스트: 신규/수정 구분, 문제 행, 빈 칸=변경 없음, 박스 설정 규칙, 회사 분리, 템플릿 왕복."""

import io  # 메모리 위의 파일
import json  # options 글자
from datetime import timedelta  # 날짜 빼기

import pytest  # 테스트 도구
from openpyxl import Workbook  # 엑셀 테스트 파일 만들기
from sqlalchemy import func, select  # 개수 세기

from app.clock import seoul_today  # 서울 기준 오늘
from app.models import InventoryMovement, Product, Supplier
from app.services import stock as stock_service  # 재고 계산
from tests.helpers import login_as  # 공통 로그인

URL = "/api/v1/product-imports"
HEADER = "SKU,품목명,기본단위,구매단가,안전재고,발주단위 이름,환산계수,발주단위 단가,최소 주문량,색상,사이즈,규격,그룹 코드\n"
COLS = {"product_col": 0, "name_col": 1, "unit_col": 2, "cost_col": 3, "safety_col": 4, "order_unit_col": 5,
        "factor_col": 6, "box_cost_col": 7, "moq_col": 8, "color_col": 9, "size_col": 10, "spec_col": 11, "group_col": 12}


def csv_file(*lines: str, header: str = HEADER) -> bytes:
    return (header + "\n".join(lines) + "\n").encode("utf-8-sig")


@pytest.fixture
def existing(world, session):
    """회사 A 의 기존 품목 OLD-1: 비활성, 기본 공급업체는 두 번째 업체, 환산계수 없음."""
    other = Supplier(company_id=world["a_company"].id, name="A2업체", lead_time_days=3)
    session.add(other)
    session.flush()
    p = Product(company_id=world["a_company"].id, sku="OLD-1", name="기존", unit="개", unit_cost=500, safety_stock=7,
                color="빨강", default_supplier_id=other.id, is_active=False)
    session.add(p)
    session.commit()
    return p


def post(client, path, content, world, filename="p.csv", **opts):
    options = {**COLS, "default_supplier_id": world["a_supplier"].id, **opts}
    return client.post(f"{URL}{path}", files={"file": (filename, content)}, data={"options": json.dumps(options)})


def products_of(session, company):
    session.expire_all()  # 앱이 바꾼 값을 다시 읽는다
    return {p.sku: p for p in session.scalars(select(Product).where(Product.company_id == company.id))}


def test_new_and_update_in_one_file(client, world, existing, session):
    """신규/수정을 구분해 미리보기하고, 반영하면 빈 칸은 그대로 두고 활성 여부·기본 공급업체는 건드리지 않는다."""
    login_as(client)
    content = csv_file("new-1,새 품목,개,\"1,200\",5,,,,,검정,M,2L,grp-a", "old-1,수정된 이름,,,,,,,,,,,", "OLD-1,중복,,,,,,,,,,,")
    preview = post(client, "/preview", content, world).json()["data"]
    assert (preview["new_count"], preview["update_count"], preview["unchanged_count"], preview["problem_count"]) == (1, 1, 0, 1)
    assert preview["new_products"][0] == {
        "row": 2, "sku": "NEW-1", "name": "새 품목", "unit": "개", "unit_cost": 1200, "safety_stock": 5, "order_unit": None,
        "units_per_box": None, "box_unit_cost": None, "min_order_units": None, "color": "검정", "size": "M", "spec": "2L", "group_code": "GRP-A"}
    assert preview["updates"] == [{"row": 3, "sku": "OLD-1", "name": "기존", "changes": [{"field": "name", "label": "품목명", "old": "기존", "new": "수정된 이름"}]}]
    assert preview["problems"][0]["reason"] == "DUPLICATE_SKU_IN_FILE" and preview["problems"][0]["row"] == 4
    assert "NEW-1" not in products_of(session, world["a_company"]) and products_of(session, world["a_company"])["OLD-1"].name == "기존"  # 미리보기는 쓰지 않는다

    assert post(client, "", content, world).status_code == 409  # 문제 행이 있으면 전체 취소
    assert "NEW-1" not in products_of(session, world["a_company"])
    done = post(client, "", content, world, exclude_problems=True)
    assert done.status_code == 201 and done.json()["data"]["created_count"] == 1 and done.json()["data"]["updated_count"] == 1
    mine = products_of(session, world["a_company"])
    assert mine["NEW-1"].default_supplier_id == world["a_supplier"].id and mine["NEW-1"].group_code == "GRP-A"
    old = mine["OLD-1"]
    assert (old.name, old.unit_cost, old.safety_stock, old.color) == ("수정된 이름", 500, 7, "빨강")  # 빈 칸은 변경 없음
    assert old.is_active is False and old.default_supplier_id != world["a_supplier"].id  # 활성 여부·공급업체는 그대로
    assert session.scalar(select(func.count()).select_from(InventoryMovement)) == 0  # 재고 이동은 만들지 않는다


def test_row_value_problems(client, world, session):
    """필수 칸 비어 있음, 환산계수 0·음수·소수, 발주단위 단가 범위 밖, SKU 비어 있음은 모두 문제 행이고 DB 는 그대로다."""
    login_as(client)
    content = csv_file(
        "N-1,,개,100,,,,,,,,,",                    # 품목명 없음
        "N-2,이름,개,,,,,,,,,,",                    # 구매단가 없음
        "N-3,이름,개,100,,BOX,0,1000,,,,,",        # 환산계수 0
        "N-4,이름,개,100,,BOX,-2,1000,,,,,",       # 환산계수 음수
        "N-5,이름,개,100,,BOX,1.5,1000,,,,,",      # 환산계수 소수
        "N-6,이름,개,100,,,,,0,,,,",               # 최소 주문량 0
        ",이름,개,100,,,,,,,,,",                    # SKU 없음
        "N-7,이름,개,abc,,,,,,,,,",                 # 단가가 숫자 아님
    )
    data = post(client, "/preview", content, world).json()["data"]
    assert data["new_count"] == 0 and data["problem_count"] == 8
    assert [p["reason"] for p in data["problems"]] == ["MISSING_REQUIRED", "MISSING_REQUIRED", "INVALID_VALUE", "INVALID_VALUE",
                                                       "INVALID_VALUE", "INVALID_VALUE", "MISSING_SKU", "INVALID_VALUE"]
    assert "환산계수" in data["problems"][2]["message"]
    assert post(client, "", content, world, exclude_problems=True).status_code == 409  # 반영할 행이 없음
    assert products_of(session, world["a_company"]) == {}


def test_missing_required_column_is_422(client, world):
    """필수 열(SKU·품목명·기본단위·구매단가) 지정이 빠지면 422, 열 번호가 겹치거나 파일 밖이어도 422."""
    login_as(client)
    content = csv_file("N-1,이름,개,100,,,,,,,,,")
    no_name = {k: v for k, v in COLS.items() if k != "name_col"}
    r = client.post(f"{URL}/preview", files={"file": ("p.csv", content)}, data={"options": json.dumps(no_name)})
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert post(client, "/preview", content, world, name_col=0).status_code == 422  # SKU 열과 겹침
    assert post(client, "/preview", content, world, color_col=40).status_code == 422  # 파일에 없는 열


def test_box_settings_merge_with_existing(client, world, session):
    """발주단위 이름·환산계수·단가·최소 주문량을 읽는다. 일부만 있으면 기존 값과 합쳐 규칙을 만족할 때만 허용한다."""
    login_as(client)
    sup = world["a_supplier"].id
    session.add_all([
        Product(company_id=world["a_company"].id, sku="BOXED", name="박스품", unit="EA", unit_cost=100, units_per_box=12,
                box_unit_cost=1100, order_unit="PACK", default_supplier_id=sup),
        Product(company_id=world["a_company"].id, sku="PLAIN", name="낱개품", unit="EA", unit_cost=100, default_supplier_id=sup),
    ])
    session.commit()
    content = csv_file(
        "NEW-OK,이름,EA,100,,CASE,24,2400,3,,,,",   # 신규: 세 값 함께 + 이름 + 최소 주문량
        "NEW-BAD,이름,EA,100,,,24,,,,,,",           # 신규: 환산계수만 → 문제
        "NEW-NAME,이름,EA,100,,CASE,,,,,,,",        # 신규: 이름만 → 문제
        "BOXED,,,,,,24,,,,,,",                      # 기존 박스 설정에 환산계수만 → 합치면 24·1100·PACK 이라 허용
        "PLAIN,,,,,,12,,,,,,",                      # 기존 박스 설정 없음 + 환산계수만 → 문제
        "PLAIN,,,,,,,,,,,,",                        # 같은 SKU 반복 → 중복 문제
    )
    data = post(client, "/preview", content, world).json()["data"]
    assert [p["reason"] for p in data["problems"]] == ["BOX_SETTINGS_INCOMPLETE", "BOX_SETTINGS_INCOMPLETE", "BOX_SETTINGS_INCOMPLETE", "DUPLICATE_SKU_IN_FILE"]
    assert [p["row"] for p in data["problems"]] == [3, 4, 6, 7]
    assert data["new_products"][0]["order_unit"] == "CASE" and data["new_products"][0]["min_order_units"] == 3
    assert data["updates"][0]["changes"] == [{"field": "units_per_box", "label": "환산계수", "old": 12, "new": 24}]
    assert post(client, "", content, world, exclude_problems=True).status_code == 201
    mine = products_of(session, world["a_company"])
    assert (mine["NEW-OK"].units_per_box, mine["NEW-OK"].box_unit_cost, mine["NEW-OK"].order_unit) == (24, 2400, "CASE")
    assert (mine["BOXED"].units_per_box, mine["BOXED"].box_unit_cost, mine["BOXED"].order_unit) == (24, 1100, "PACK")
    assert mine["PLAIN"].units_per_box is None


def test_factor_only_with_unit_cost_defaults_order_unit_name(client, world, session):
    """신규 품목에 환산계수·단가만 있고 이름이 없으면 품목 등록처럼 "박스"가 채워진다."""
    login_as(client)
    assert post(client, "", csv_file("N-1,이름,EA,100,,,10,900,,,,,"), world).status_code == 201
    assert products_of(session, world["a_company"])["N-1"].order_unit == "박스"


def test_unchanged_rows_are_counted_not_applied(client, world, existing):
    """파일 값이 기존과 같으면 "변경 없음"으로 세고, 전부 그렇다면 반영할 행이 없어 409."""
    login_as(client)
    content = csv_file("OLD-1,기존,개,500,7,,,,,빨강,,,")
    assert post(client, "/preview", content, world).json()["data"]["unchanged_count"] == 1
    assert post(client, "", content, world).json()["error"]["code"] == "NOTHING_TO_IMPORT"


def test_preview_changed_before_commit(client, world, session):
    """미리보기 뒤 다른 사용자가 같은 SKU 를 먼저 등록하면, 확정 때 그 행은 수정으로 처리되고 응답이 알려 준다."""
    login_as(client)
    content = csv_file("RACE-1,새 이름,개,300,,,,,,,,,")
    preview = post(client, "/preview", content, world).json()["data"]
    assert (preview["new_count"], preview["update_count"]) == (1, 0)
    session.add(Product(company_id=world["a_company"].id, sku="RACE-1", name="먼저 등록", unit="개", unit_cost=100,
                        default_supplier_id=world["a_supplier"].id))
    session.commit()
    done = post(client, "", content, world, expected_new_count=1, expected_update_count=0).json()["data"]
    assert (done["created_count"], done["updated_count"], done["preview_changed"]) == (0, 1, True)
    assert "신규 1→0건, 수정 0→1건" in done["message"]
    assert products_of(session, world["a_company"])["RACE-1"].name == "새 이름"
    # 같은 결과면 알리지 않는다
    again = post(client, "", csv_file("RACE-1,또 바꿈,개,300,,,,,,,,,"), world, expected_new_count=0, expected_update_count=1).json()["data"]
    assert again["preview_changed"] is False and again["message"] is None


def test_new_product_needs_supplier_and_other_company_untouched(client, world, existing, session):
    """새 품목이 있으면 공급업체가 필수(다른 회사 업체는 404). 회사 B 로 올려도 A 의 같은 SKU 는 그대로다."""
    login_as(client, "admin@b.test")
    content = csv_file("OLD-1,B의 품목,개,900,,,,,,,,,")
    no_supplier = client.post(URL, files={"file": ("p.csv", content)}, data={"options": json.dumps(COLS)})
    assert no_supplier.status_code == 422
    assert post(client, "", content, world, default_supplier_id=world["a_supplier"].id).status_code == 404  # A 회사 업체
    done = post(client, "", content, world, default_supplier_id=world["b_supplier"].id)
    assert done.status_code == 201 and done.json()["data"]["created_count"] == 1  # B 에서는 신규
    assert products_of(session, world["a_company"])["OLD-1"].name == "기존"
    assert products_of(session, world["b_company"])["OLD-1"].name == "B의 품목"


def test_xlsx_cp949_and_limits(client, world):
    """.xlsx(숫자 칸 포함)와 CP949 CSV 도 읽고, 5,000행·5MB 경계가 기존과 같다."""
    login_as(client)
    wb = Workbook()
    for r in ([h for h in HEADER.strip().split(",")], ["X-1", "엑셀", "EA", 1200.0, 3, None, None, None, None, None, None, None, None]):
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    assert post(client, "/preview", buf.getvalue(), world, filename="p.xlsx").json()["data"]["new_count"] == 1
    cp949 = (HEADER + "C-1,한글품목,개,100,,,,,,,,,\n").encode("cp949")
    assert post(client, "/preview", cp949, world).json()["data"]["new_products"][0]["name"] == "한글품목"
    assert post(client, "/preview", b"not a zip", world, filename="p.xlsx").status_code == 422
    exactly = csv_file(*[f"S-{i},이름,개,1,,,,,,,,," for i in range(5000)])
    assert post(client, "/preview", exactly, world).json()["data"]["new_count"] == 5000
    many = csv_file(*[f"S-{i},이름,개,1,,,,,,,,," for i in range(5001)])
    assert post(client, "/preview", many, world).json()["error"]["code"] == "TOO_MANY_ROWS"
    assert post(client, "/preview", b"a" * (5 * 1024 * 1024 + 1), world).json()["error"]["code"] == "FILE_TOO_LARGE"


def test_auth_required(client, world):
    assert client.post(f"{URL}/inspect", files={"file": ("p.csv", b"a")}).status_code == 401
    assert client.get("/api/v1/import-templates/products.csv").status_code == 401


# ---------- 템플릿 ----------

@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_product_template_round_trip(client, world, session, fmt):
    """품목 템플릿을 내려받아 그대로 올리면 열이 자동으로 잡히고 오류 없이 신규 1건으로 반영된다."""
    login_as(client)
    r = client.get(f"/api/v1/import-templates/products.{fmt}")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    if fmt == "csv":
        assert r.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    name = f"products-template.{fmt}"
    inspected = client.post(f"{URL}/inspect", files={"file": (name, r.content)}).json()["data"]
    assert inspected["row_count"] == 1 and all(v is not None for v in inspected["suggested"].values())
    options = {**inspected["suggested"], "default_supplier_id": world["a_supplier"].id}
    preview = client.post(f"{URL}/preview", files={"file": (name, r.content)}, data={"options": json.dumps(options)}).json()["data"]
    assert (preview["new_count"], preview["problem_count"]) == (1, 0)
    assert client.post(URL, files={"file": (name, r.content)}, data={"options": json.dumps(options)}).status_code == 201
    assert products_of(session, world["a_company"])["EX-001"].order_unit == "BOX"


@pytest.mark.parametrize("fmt", ["csv", "xlsx"])
def test_sales_template_round_trip(client, world, session, fmt):
    """판매 템플릿을 그대로 올리면 열이 자동으로 잡히고, 품목·재고가 있으면 오류 없이 미리보기된다."""
    login_as(client)
    p = Product(company_id=world["a_company"].id, sku="EX-001", name="예시", unit="EA", unit_cost=1, default_supplier_id=world["a_supplier"].id)
    session.add(p)
    session.flush()
    stock_service.register_movement(world["a_company"].id, session, world["a_staff"].id, product_id=p.id, movement_type="RECEIPT",
                                    direction="IN", quantity=10, movement_date=seoul_today() - timedelta(days=30))
    session.commit()
    r = client.get(f"/api/v1/import-templates/sales.{fmt}")
    assert r.status_code == 200
    name = f"sales-template.{fmt}"
    sales = "/api/v1/sales-imports"
    inspected = client.post(f"{sales}/inspect", files={"file": (name, r.content)}).json()["data"]
    s = inspected["suggested"]
    assert all(v is not None for v in s.values())
    options = {"product_col": s["product_col"], "quantity_col": s["quantity_col"], "date_col": s["date_col"], "ref_col": s["ref_col"],
               "status_col": s["status_col"], "statuses": ["배송완료"], "option_col": s["option_col"], "sales_channel": "SMARTSTORE"}
    preview = client.post(f"{sales}/preview", files={"file": (name, r.content)}, data={"options": json.dumps(options)}).json()["data"]
    assert (preview["apply_count"], preview["problem_count"]) == (1, 0)


def test_unknown_template_is_404(client, world):
    login_as(client)
    assert client.get("/api/v1/import-templates/orders.csv").status_code == 404
    assert client.get("/api/v1/import-templates/products.pdf").status_code == 404
