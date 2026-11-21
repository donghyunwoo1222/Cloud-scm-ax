"""발주서 상태 표 (#260 PR2). 상태가 바뀌는 이동과 동작별 허용 상태를 이 파일 한 곳에 모은다.

다른 서비스를 import 하지 않는다: stock.py 처럼 purchase_orders.py 를 불러올 수 없는 곳(순환 import)도 이 표를 읽게.
상태를 실제로 바꾸는 함수는 purchase_orders.set_status 하나뿐이다. 새 상태·동작을 넣을 때는 docs/06-system-design/state-machines.md 를 함께 고친다.
"""

# 상태가 바뀌는 이동 표 (#34). 동작 → (출발할 수 있는 상태들, 도착 상태). 여기 없는 이동은 409 INVALID_STATUS
TRANSITIONS = {
    "approve": ({"DRAFT"}, "APPROVED"),  # 승인 (관리자만, 경로에서 검사)
    "order": ({"APPROVED"}, "ORDERED"),  # 공급업체에 발주했음 표시
    "cancel": ({"DRAFT", "APPROVED", "ORDERED"}, "CANCELLED"),  # 취소 (입고 기록이 한 번도 없을 때만)
    "email": ({"APPROVED"}, "ORDERED"),  # 메일 첫 발송 (po_mail.py, 발송 성공 뒤에만). 다시 보내기는 상태가 안 바뀐다
    "complete_receipt": ({"ORDERED"}, "RECEIVED"),  # 입고 완료 (모든 줄이 다 찼을 때만, 부분 입고는 ORDERED 그대로)
    "close_remaining": ({"ORDERED"}, "RECEIVED"),  # 잔량 마감 (#252): 입고 기록이 있을 때만, 사유 필수. 못 온 수량은 더 기다리지 않는다
}

# 상태를 바꾸지 않는(또는 바꾸기 전에 먼저 보는) 동작 → 허용 상태. 이 밖의 상태면 각 호출 지점이 409 INVALID_STATUS
ACTION_STATES = {
    "edit": ("DRAFT",),  # 발주서 수정 (승인 이후 수정 불가)
    "email": ("APPROVED", "ORDERED"),  # 메일 보내기·미리보기: 승인됨(첫 발송) · 발주함(다시 보내기)
    "receive": ("ORDERED",),  # 입고 등록
    "correct_receipt": ("ORDERED",),  # 발주 입고 정정 (RECEIVED 가 되면 정정 불가)
    "remind": ("ORDERED",),  # 납기 지연 독촉 메일 (#269). 상태는 바꾸지 않는다. 지연 여부는 receipt_due_condition 으로 따로 본다
    "supplier_reply": ("ORDERED",),  # 직원이 받은 공급업체 회신 기록 (#265 PR4). 부분 입고여도 가능, 입고 완료·잔량 마감 뒤에는 불가
    "document": ("APPROVED", "ORDERED", "RECEIVED"),  # 발주서 문서(PDF·엑셀) 보기: 승인 이후만
}

# 상태 코드 → 화면에 보이는 한국어 이름 (오류 문장용, 프런트 lib/po.ts STATUS_LABEL 과 같은 글자)
STATUS_NAMES = {
    "DRAFT": "작성 중",
    "APPROVED": "승인됨",
    "ORDERED": "발주함",
    "RECEIVED": "입고 완료",
    "CANCELLED": "취소됨",
}


def allowed_actions(status: str, role: str, has_receipts: bool, overdue: bool = False) -> list[str]:
    """이 발주서에서 지금 누를 수 있는 동작 (#260 PR3). 화면 버튼은 이 목록만 따른다.

    상태 조건은 위 두 표에서 읽는다(표를 두 벌 두지 않는다). 상태 밖 조건은 두 개뿐이다:
    승인은 관리자만(api 의 AdminUser), 취소는 입고 기록이 0건일 때만(change_status 의 CANNOT_CANCEL_RECEIVED),
    잔량 마감은 입고 기록이 1건 이상일 때만(close_remaining 의 NO_RECEIPTS). 취소와 잔량 마감은 정확히 반대 조건이다.
    독촉(#269)은 overdue 일 때만: 호출한 쪽이 스위치 켜짐 + receipt_due_condition("OVERDUE") 로 구해 넘긴다(기본 False = 버튼 없음).
    횟수·간격 한도는 여기서 보지 않는다(이력 조회가 필요): 미리보기가 이유를 보여 주고 발송이 409 로 막는다.
    예) ORDERED · 담당자 · 입고 없음 → ["cancel", "email", "receive", "supplier_reply", "document"]
        ORDERED · 담당자 · 입고 있음 → ["close_remaining", "email", "receive", "supplier_reply", "document"]
    """
    checks = {
        "edit": status in ACTION_STATES["edit"],
        "approve": status in TRANSITIONS["approve"][0] and role == "ADMIN",
        "order": status in TRANSITIONS["order"][0],
        "cancel": status in TRANSITIONS["cancel"][0] and not has_receipts,
        "close_remaining": status in TRANSITIONS["close_remaining"][0] and has_receipts,  # 역할 무관 (취소와 같은 권한)
        "email": status in ACTION_STATES["email"],  # ORDERED 는 다시 보내기
        "remind": status in ACTION_STATES["remind"] and overdue,  # 역할 무관 (메일 보내기와 같은 권한)
        "receive": status in ACTION_STATES["receive"],
        "supplier_reply": status in ACTION_STATES["supplier_reply"],  # 역할 무관 (전화를 받는 담당자도)
        "document": status in ACTION_STATES["document"],
    }
    return [action for action, ok in checks.items() if ok]  # 순서는 위 딕셔너리 순서 그대로
