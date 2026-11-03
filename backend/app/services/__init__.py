# 업무 규칙 층: 재고·발주 상태·추천 계산
# 규칙(R1, #23): 로그인 후 쓰는 service 함수는 company_id 를 첫 번째 인자로 받는다. 예) list_suppliers(company_id, db, ...)
#   company_id 는 경로 함수가 토큰 사용자(CurrentUser)에서 꺼내 넘긴다. 요청 본문의 값은 절대 쓰지 않는다.
#   로그인 전에 쓰는 auth.py(가입·로그인 확인)는 아직 회사가 정해지지 않았으므로 예외다.
