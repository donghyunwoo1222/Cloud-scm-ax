"""테스트 DB 보호 (#71 A): 접속 DB 이름이 scm_test 또는 scm_test_<소문자·숫자·밑줄> 이 아니면 아무것도 지우지 않고 테스트를 멈춘다.

진짜 DB 에 접속하지 않도록, 지우는 함수들을 '불렸는지 기록만 하는 가짜'로 바꿔 끼운 뒤 확인한다.
"""

import pytest  # 테스트 도구

from tests import conftest  # 검사할 초기화 함수가 있는 곳


@pytest.mark.parametrize("url", [
    "postgresql+psycopg://scm:pw@localhost:5433/scm",  # 개발 DB
    "postgresql+psycopg://scm:pw@localhost:5433/scm_testing",  # scm_test 로 시작만 하고 밑줄 구분이 없는 DB
    "postgresql+psycopg://scm:pw@localhost:5433/scm_test-x",  # 허용 글자(소문자·숫자·밑줄) 밖의 글자
    "postgresql+psycopg://scm:pw@localhost:5433/prod",  # 전혀 다른 DB
    "postgresql+psycopg://scm:pw@localhost:5433/SCM_TEST",  # 대소문자만 다른 DB
    "postgresql+psycopg://scm:pw@localhost:5433",  # DB 이름이 없는 주소
])
def test_reset_refuses_other_databases(monkeypatch, url):
    calls = []  # 불린 '지우기·만들기' 함수 기록
    monkeypatch.setattr(conftest, "create_test_database_if_missing", lambda u: calls.append("create"))  # DB 만들기 대신 기록
    monkeypatch.setattr(conftest.command, "downgrade", lambda *a: calls.append("downgrade"))  # 표 지우기 대신 기록
    monkeypatch.setattr(conftest.command, "upgrade", lambda *a: calls.append("upgrade"))  # 표 만들기 대신 기록
    with pytest.raises(pytest.exit.Exception):  # 테스트 전체가 멈춘다 (pytest.exit)
        conftest.reset_database(url)
    assert calls == []  # 아무 DB 에도 손대지 않았다


@pytest.mark.parametrize("name", ["scm_test", "scm_test_181", "scm_test_a_b2"])
def test_allowed_test_db_names(name):
    assert conftest.is_test_db_name(name)  # 정확히 scm_test, 또는 scm_test_ 뒤에 소문자·숫자·밑줄


@pytest.mark.parametrize("name", ["scm", "scm_testing", "scm_test-x", "prod", "scm_test_", "scm_test_Ab", "SCM_TEST", "", None])
def test_rejected_test_db_names(name):
    assert not conftest.is_test_db_name(name)  # 개발 DB·비슷한 이름·빈 이름은 거부 (DB 에는 접속하지 않는다)
