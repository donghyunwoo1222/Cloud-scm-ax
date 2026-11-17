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
}

# 상태를 바꾸지 않는(또는 바꾸기 전에 먼저 보는) 동작 → 허용 상태. 이 밖의 상태면 각 호출 지점이 409 INVALID_STATUS
ACTION_STATES = {
    "edit": ("DRAFT",),  # 발주서 수정 (승인 이후 수정 불가)
    "email": ("APPROVED", "ORDERED"),  # 메일 보내기·미리보기: 승인됨(첫 발송) · 발주함(다시 보내기)
    "receive": ("ORDERED",),  # 입고 등록
    "correct_receipt": ("ORDERED",),  # 발주 입고 정정 (RECEIVED 가 되면 정정 불가)
    "document": ("APPROVED", "ORDERED", "RECEIVED"),  # 발주서 문서(PDF·엑셀) 보기: 승인 이후만
}
