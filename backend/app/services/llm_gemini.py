"""Gemini REST 어댑터(#180). llm.ask() 만 이 파일을 쓴다. 기능 코드는 이 파일을 직접 부르지 않는다.

새 라이브러리 없이 표준 urllib 로 generateContent 를 부른다. 이 파일은 오류를 세 가지로만 나눠 돌려준다.
- 429·5xx·연결 끊김 → LLMRetryable, 시간 초과 → TimeoutError: llm.ask 가 짧게 다시 시도한다
- 그 밖(400·401·403·404, 이상한 응답, 너무 큰 응답, 리다이렉트) → GeminiError: 다시 해도 같아 바로 실패한다
어느 쪽이든 마지막에는 llm.ask 가 503 LLM_UNAVAILABLE 로 바꿔 호출자가 수동 입력으로 돌아가게 한다.

키: x-goog-api-key 헤더로만 보낸다(주소에 넣지 않는다). 오류 문장에는 상태 코드만 넣고 키·주소·응답 본문은 넣지 않는다.
주의(무료 키): 무료 키의 입력·출력은 구글의 제품 개선·모델 개발에 쓰이고 사람이 검수할 수 있다.
민감 데이터(실제 고객·거래처·가격 등)는 보내지 않는다. 실제 고객 데이터는 결제가 연결된 유료 키가 필요하다.
"""

import json  # 요청·응답 본문 (JSON)
import urllib.error  # HTTP 오류 종류
import urllib.request  # 표준 HTTP 클라이언트 (새 라이브러리 없음)
from urllib.parse import quote  # 모델 이름을 주소에 안전하게 넣기

from app.config import settings  # LLM_* 설정
from app.services.llm import LLMReply, LLMRetryable  # 래퍼가 정한 응답 모양·재시도 오류

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"  # Gemini API 주소 (HTTPS 만)


class GeminiError(Exception):
    """다시 시도해도 같은 오류. 문장에는 상태 코드 같은 짧은 설명만 넣는다(키·본문 금지)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다. urllib 은 리다이렉트 때 헤더를 그대로 옮겨 키가 다른 주소로 갈 수 있기 때문."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # None 이면 3xx 가 HTTPError 로 올라와 GeminiError 가 된다


_opener = urllib.request.build_opener(_NoRedirect)  # 이 어댑터 전용 연결 도구. 테스트는 가짜로 바꿔 끼운다


class GeminiClient:
    def complete(self, system: str, user: str, timeout: float) -> LLMReply:
        """지시(system)와 데이터(user)를 다른 칸에 담아 한 번 부른다. 재시도는 llm.ask 가 한다."""
        body = {
            "systemInstruction": {"parts": [{"text": system}]},  # 지시문·스키마는 system 칸에만
            "contents": [{"role": "user", "parts": [{"text": user}]}],  # 구분자로 감싼 데이터는 user 칸에만
            "generationConfig": {
                "responseMimeType": "application/json",  # JSON 으로만 답하게 한다 (검증은 llm.ask 의 Pydantic)
                "maxOutputTokens": settings.llm_max_output_tokens,  # 출력 길이(=비용) 상한
            },
        }
        request = urllib.request.Request(
            f"{BASE_URL}/{quote(settings.llm_model, safe='')}:generateContent",  # 주소에는 모델 이름만, 키는 없다
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "x-goog-api-key": settings.llm_api_key.get_secret_value()},  # 키는 헤더로만
            method="POST",
        )
        limit = settings.llm_max_response_bytes
        try:
            with _opener.open(request, timeout=timeout) as response:
                raw = response.read(limit + 1)  # 상한보다 1바이트 더 읽어 넘쳤는지만 본다
        except urllib.error.HTTPError as exc:  # 서버가 오류 상태로 답함
            exc.close()  # 오류 응답 본문은 읽지 않고 닫는다
            if exc.code == 429 or exc.code >= 500:  # 호출 한도 초과·서버 과부하: 잠깐 뒤 될 수 있다
                raise LLMRetryable(f"HTTP {exc.code}") from None
            raise GeminiError(f"HTTP {exc.code}") from None  # 400·401·403·404·3xx: 다시 해도 같다
        except TimeoutError:  # 시간 초과 (socket.timeout 도 TimeoutError)
            raise TimeoutError("timeout") from None
        except urllib.error.URLError as exc:  # 연결 실패 (이유가 시간 초과일 수도 있다)
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError("timeout") from None
            raise LLMRetryable("connection") from None
        except OSError:  # 연결이 중간에 끊김 등
            raise LLMRetryable("connection") from None
        if len(raw) > limit:
            raise GeminiError("response too large")
        try:
            data = json.loads(raw)
            text = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
            usage = data.get("usageMetadata") or {}
            tokens_in = int(usage.get("promptTokenCount", 0))
            # 생각(thinking) 토큰도 출력 요금으로 센다고 보고 더한다 (shortcut: 유료 전환 때 요금표로 확인)
            tokens_out = int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            raise GeminiError("unexpected response") from None  # 후보가 없음(차단 등)·모양이 다름
        cost = (tokens_in * settings.llm_price_input_usd_per_mtok
                + tokens_out * settings.llm_price_output_usd_per_mtok) / 1_000_000  # 예) 입력 1,000·단가 0.1 → $0.0001
        return LLMReply(text=text, cost_usd=cost)
