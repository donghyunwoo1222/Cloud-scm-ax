"""Gemini 어댑터(#180) 테스트. 연결 도구(_opener)를 가짜로 바꿔 끼워 실제 네트워크·실제 키는 쓰지 않는다."""

import io  # 가짜 응답 본문
import json  # 요청·응답 본문
import logging  # caplog
import urllib.error  # 가짜 HTTP 오류

import pytest  # 테스트 도구
from pydantic import SecretStr  # 가짜 키를 설정에 넣는 모양

from app.config import settings  # LLM_* 설정을 바꿔 끼운다
from app.services import llm, llm_gemini  # 래퍼와 어댑터
from app.services.llm import LLMOutput, LLMRetryable, LLMUnavailable
from app.services.llm_gemini import GeminiClient, GeminiError

FAKE_KEY = "fake-test-key-NOT-REAL-0001"  # 테스트 전용 가짜 키 (실제 키 아님)


def gemini_body(text='{"column": "B"}', usage=None):
    """Gemini 응답 모양을 흉내 낸 본문."""
    body = {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    if usage is not None:
        body["usageMetadata"] = usage
    return json.dumps(body).encode()


class FakeOpener:
    """정해 둔 순서대로 응답하거나 오류를 던진다. 받은 요청과 timeout 을 기록한다."""

    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        step = self.steps.pop(0) if len(self.steps) > 1 else self.steps[0]
        if isinstance(step, BaseException):
            raise step
        return io.BytesIO(step)  # with 문과 read(n) 을 지원한다


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "error", {}, io.BytesIO(b"body"))


@pytest.fixture
def gemini(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", SecretStr(FAKE_KEY))
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "llm_max_output_tokens", 256)
    monkeypatch.setattr(settings, "llm_max_response_bytes", 10_000)
    monkeypatch.setattr(settings, "llm_price_input_usd_per_mtok", 0.0)
    monkeypatch.setattr(settings, "llm_price_output_usd_per_mtok", 0.0)


def use(monkeypatch, steps):
    fake = FakeOpener(steps)
    monkeypatch.setattr(llm_gemini, "_opener", fake)
    return fake


def test_request_shape_key_only_in_header(gemini, monkeypatch):
    fake = use(monkeypatch, [gemini_body()])
    reply = GeminiClient().complete("지시문", "<data-x>\n{}\n</data-x>", timeout=7.5)
    assert reply.text == '{"column": "B"}' and reply.cost_usd == 0  # 무료 키(단가 0)는 비용 0
    request, timeout = fake.requests[0]
    assert timeout == 7.5
    assert request.full_url == f"{llm_gemini.BASE_URL}/test-model:generateContent"
    assert FAKE_KEY not in request.full_url and "key=" not in request.full_url  # 주소에 키 없음
    assert request.get_header("X-goog-api-key") == FAKE_KEY  # 키는 헤더로만
    body = json.loads(request.data)
    assert body["systemInstruction"]["parts"][0]["text"] == "지시문"  # 지시는 system 칸
    assert body["contents"] == [{"role": "user", "parts": [{"text": "<data-x>\n{}\n</data-x>"}]}]  # 데이터는 user 칸
    assert body["generationConfig"] == {"responseMimeType": "application/json", "maxOutputTokens": 256}


def test_cost_from_tokens_and_prices(gemini, monkeypatch):
    """입력 1,000 × $0.1 + 출력(500 + 생각 100) × $0.4, 100만 토큰당 → $0.00034."""
    monkeypatch.setattr(settings, "llm_price_input_usd_per_mtok", 0.1)
    monkeypatch.setattr(settings, "llm_price_output_usd_per_mtok", 0.4)
    use(monkeypatch, [gemini_body(usage={"promptTokenCount": 1000, "candidatesTokenCount": 500,
                                         "thoughtsTokenCount": 100})])
    assert GeminiClient().complete("s", "u", 1).cost_usd == pytest.approx(0.00034)


@pytest.mark.parametrize("error,expected", [
    (http_error(429), LLMRetryable),  # 호출 한도 초과
    (http_error(500), LLMRetryable),
    (http_error(503), LLMRetryable),
    (TimeoutError("timed out"), TimeoutError),
    (urllib.error.URLError(TimeoutError("timed out")), TimeoutError),
    (urllib.error.URLError(ConnectionRefusedError("refused")), LLMRetryable),
    (ConnectionResetError("reset"), LLMRetryable),
    (http_error(400), GeminiError),  # 잘못된 요청: 다시 해도 같다
    (http_error(401), GeminiError),  # 키 틀림
    (http_error(403), GeminiError),
    (http_error(404), GeminiError),  # 없는 모델 이름
    (http_error(302), GeminiError),  # 리다이렉트는 따라가지 않는다
])
def test_error_mapping_without_key(gemini, monkeypatch, error, expected):
    use(monkeypatch, [error])
    with pytest.raises(expected) as info:
        GeminiClient().complete("s", "u", 1)
    assert FAKE_KEY not in repr(info.value) and FAKE_KEY not in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__  # 원래 오류(주소·본문)가 따라가지 않는다


def test_redirect_is_not_followed():
    assert llm_gemini._NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://other.example") is None


@pytest.mark.parametrize("raw", [
    b"not json",
    json.dumps({"candidates": []}).encode(),  # 후보 없음 (차단 등)
    json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode(),
    json.dumps({"candidates": [{"content": {}}]}).encode(),
])
def test_unexpected_response_is_not_retried(gemini, monkeypatch, raw):
    use(monkeypatch, [raw])
    with pytest.raises(GeminiError):
        GeminiClient().complete("s", "u", 1)


def test_response_size_limit(gemini, monkeypatch):
    monkeypatch.setattr(settings, "llm_max_response_bytes", 50)
    use(monkeypatch, [gemini_body(text="x" * 100)])
    with pytest.raises(GeminiError, match="too large"):
        GeminiClient().complete("s", "u", 1)


def test_default_client_needs_key_and_model(gemini, monkeypatch):
    assert isinstance(llm.default_client(), GeminiClient)
    monkeypatch.setattr(settings, "llm_model", "")  # 모델 이름 없음
    assert llm.default_client() is None
    monkeypatch.setattr(settings, "llm_model", "test-model")
    monkeypatch.setattr(settings, "llm_api_key", SecretStr(""))  # 키 없음 (CI 와 같음)
    assert llm.default_client() is None


def test_key_hidden_in_settings_repr(gemini):
    assert FAKE_KEY not in repr(settings) and FAKE_KEY not in str(settings.llm_api_key)


class Pick(LLMOutput):
    column: str


@pytest.fixture
def through_ask(gemini, monkeypatch):
    """래퍼 → 어댑터 → 가짜 HTTP 를 끝까지 잇는다. 기다림은 건너뛴다."""
    llm.reset()
    for name, value in (("llm_enabled", True), ("llm_daily_calls_per_company", 100), ("llm_monthly_budget_usd", 1.0),
                        ("llm_timeout_seconds", 8.0), ("llm_deadline_seconds", 20.0), ("llm_max_retries", 2),
                        ("llm_retry_wait_seconds", 0.5), ("llm_max_input_chars", 20_000)):
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(llm, "client", GeminiClient())
    monkeypatch.setattr(llm, "sleep", lambda seconds: None)
    monkeypatch.setitem(llm.PROMPTS, "test", "열을 골라라.")
    monkeypatch.setattr(llm.log, "disabled", False)  # 같은 실행의 alembic fileConfig 가 꺼 둔 로거를 다시 켠다
    yield
    llm.reset()


def test_ask_success_through_gemini(through_ask, monkeypatch):
    use(monkeypatch, [gemini_body()])
    assert llm.ask(1, "test", {"headers": ["수량"]}, Pick) == Pick(column="B")


def test_ask_429_retries_then_falls_back(through_ask, monkeypatch, caplog):
    """429 가 계속되면 3번 시도 뒤 503 LLM_UNAVAILABLE: 호출자는 수동 입력으로 돌아간다. 로그·오류에 키가 없다."""
    fake = use(monkeypatch, [http_error(429)])
    with caplog.at_level(logging.INFO, logger="app.services.llm"), pytest.raises(LLMUnavailable) as info:
        llm.ask(1, "test", {"headers": ["수량"]}, Pick)
    assert (info.value.status, info.value.code, info.value.details) == (503, "LLM_UNAVAILABLE", {"reason": "UPSTREAM"})
    assert len(fake.requests) == 3
    assert "outcome=UPSTREAM error=LLMRetryable" in caplog.text
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in repr(info.value)


def test_ask_auth_error_is_not_retried(through_ask, monkeypatch):
    fake = use(monkeypatch, [http_error(401)])
    with pytest.raises(LLMUnavailable):
        llm.ask(1, "test", {}, Pick)
    assert len(fake.requests) == 1
