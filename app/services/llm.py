"""LLM 서비스 - Ollama qwen2.5-coder:7b 연동

Ollama HTTP API를 통해 로컬 LLM으로 답변을 생성한다.
"""
from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator

import httpx

from app.config import settings

# RAG 프롬프트 템플릿
RAG_PROMPT_TEMPLATE = """다음은 채팅 로그에서 검색된 관련 내용입니다.
이 내용을 참고하여 사용자의 질문에 한글로 정확하게 답변해주세요.
검색된 내용에 없는 정보는 추측하지 마세요.

=== 검색된 컨텍스트 ===
{context}
========================

질문: {prompt}

답변:"""

_proxy_request_lock: asyncio.Lock | None = None
_PROXY_MAX_RETRIES = 2
_PROXY_RETRY_BASE_DELAY = 0.75


def _get_proxy_request_lock() -> asyncio.Lock:
    """로컬 프록시 동시 요청 직렬화를 위한 단일 락"""
    global _proxy_request_lock
    if _proxy_request_lock is None:
        _proxy_request_lock = asyncio.Lock()
    return _proxy_request_lock


class ProxyLLMError(RuntimeError):
    """프록시 호출 실패를 표현하는 예외"""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"프록시 LLM 호출 실패 ({status_code}): {message}")


class BaseLLM(ABC):
    """LLM 추상 기본 클래스"""

    @abstractmethod
    async def generate(self, prompt: str, context: str) -> str:
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str, context: str) -> AsyncIterator[str]:
        """스트리밍 답변 생성

        Yields:
            생성되는 토큰 문자열
        """
        ...


class OllamaLLM(BaseLLM):
    """Ollama 기반 LLM 구현체"""

    def __init__(self, model: str | None = None):
        self.model = model or settings.llm_model
        self.base_url = settings.ollama_base_url

    async def generate(self, prompt: str, context: str) -> str:
        """컨텍스트 기반 답변 생성

        Args:
            prompt: 사용자 질의
            context: RAG로 검색된 관련 컨텍스트

        Returns:
            생성된 답변 문자열
        """
        full_prompt = RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                },
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()["response"]

    async def generate_stream(self, prompt: str, context: str) -> AsyncIterator[str]:
        """스트리밍 답변 생성

        Args:
            prompt: 사용자 질의
            context: RAG로 검색된 관련 컨텍스트

        Yields:
            생성되는 토큰 문자열
        """
        full_prompt = RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={"model": self.model, "prompt": full_prompt, "stream": True},
                timeout=300.0,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        data = json.loads(line)
                        if "response" in data:
                            yield data["response"]


class ProxyLLM(BaseLLM):
    """CLIProxyAPI 프록시를 통한 LLM 구현

    OpenAI 호환 /v1/chat/completions 엔드포인트를 사용하며,
    model 필드로 프록시가 노출한 모델명(alias 포함)을 지정한다.
    API 직접 호출 없이 프록시만 사용한다.
    """

    def __init__(
        self,
        model: str | None = None,
        proxy_url: str | None = None,
        api_key: str | None = None,
    ):
        self.model = model or settings.claude_model
        self.proxy_url = proxy_url or settings.proxy_api_url
        self.api_key = api_key if api_key is not None else settings.proxy_api_key
        self.endpoint = f"{self.proxy_url}/v1/chat/completions"

    async def generate(self, prompt: str, context: str) -> str:
        """프록시를 통한 답변 생성

        Args:
            prompt: 사용자 질의
            context: RAG로 검색된 관련 컨텍스트

        Returns:
            생성된 답변 문자열
        """
        full_prompt = RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)

        # 로컬 Codex OAuth auth가 1개인 경우 동시 completion이 auth_unavailable로 실패할 수 있다.
        async with _get_proxy_request_lock():
            for attempt in range(_PROXY_MAX_RETRIES + 1):
                try:
                    async with httpx.AsyncClient() as client:
                        response = await client.post(
                            self.endpoint,
                            json=self._build_payload(full_prompt, stream=False),
                            headers=self._build_headers(),
                            timeout=300.0,
                        )
                        await self._raise_for_status_async(response)
                        data = response.json()
                        return _extract_chat_completion_content(data)
                except (ProxyLLMError, httpx.HTTPError) as exc:
                    if not self._should_retry(exc, attempt):
                        raise
                    await asyncio.sleep(self._retry_delay(attempt))

    async def generate_stream(self, prompt: str, context: str) -> AsyncIterator[str]:
        """프록시를 통한 스트리밍 답변 생성

        Args:
            prompt: 사용자 질의
            context: RAG로 검색된 관련 컨텍스트

        Yields:
            생성되는 토큰 문자열
        """
        full_prompt = RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)

        async with _get_proxy_request_lock():
            for attempt in range(_PROXY_MAX_RETRIES + 1):
                emitted_any = False
                try:
                    async with httpx.AsyncClient() as client:
                        async with client.stream(
                            "POST",
                            self.endpoint,
                            json=self._build_payload(full_prompt, stream=True),
                            headers=self._build_headers(),
                            timeout=300.0,
                        ) as response:
                            await self._raise_for_status_async(response)
                            async for line in response.aiter_lines():
                                if line.strip() and line.startswith("data: "):
                                    data_str = line[6:]  # "data: " 제거
                                    if data_str == "[DONE]":
                                        return
                                    data = json.loads(data_str)
                                    if "choices" in data and len(data["choices"]) > 0:
                                        delta = data["choices"][0].get("delta", {})
                                        for chunk in _extract_delta_contents(delta):
                                            emitted_any = True
                                            yield chunk
                            return
                except (ProxyLLMError, httpx.HTTPError) as exc:
                    if emitted_any or not self._should_retry(exc, attempt):
                        raise
                    await asyncio.sleep(self._retry_delay(attempt))

    def _build_payload(self, full_prompt: str, *, stream: bool) -> dict[str, Any]:
        """프록시 chat.completions payload 생성"""
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "채팅 로그 기반 RAG 시스템입니다."},
                {"role": "user", "content": full_prompt},
            ],
            "stream": stream,
        }

    def _build_headers(self) -> dict[str, str]:
        """프록시 인증 헤더 생성"""
        api_key = self.api_key.strip()
        if not api_key:
            raise RuntimeError(
                "PROXY_API_KEY가 설정되지 않았습니다. "
                "프록시 LLM 사용 시 .env에 PROXY_API_KEY를 추가하세요."
            )
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """프록시 에러를 읽기 쉬운 메시지로 변환"""
        if response.status_code < 400:
            return

        try:
            payload = response.json()
        except ValueError:
            message = response.text.strip() or response.reason_phrase
        else:
            message = _extract_proxy_error_message(payload, response.reason_phrase)

        raise ProxyLLMError(response.status_code, message)

    @staticmethod
    async def _raise_for_status_async(response: httpx.Response) -> None:
        """stream 응답까지 포함해 프록시 에러를 안전하게 읽는다"""
        if response.status_code < 400:
            return

        message = response.reason_phrase
        read_body = getattr(response, "aread", None)
        if callable(read_body):
            try:
                raw = await read_body()
            except Exception:
                raw = b""
            else:
                message = _extract_proxy_error_message_from_bytes(raw, message)

        if message == response.reason_phrase:
            try:
                payload = response.json()
            except Exception:
                text = getattr(response, "text", "")
                if isinstance(text, str) and text.strip():
                    message = text.strip()
            else:
                message = _extract_proxy_error_message(payload, message)

        raise ProxyLLMError(response.status_code, message)

    @staticmethod
    def _should_retry(exc: Exception, attempt: int) -> bool:
        """일시적 프록시 실패 여부 판단"""
        if attempt >= _PROXY_MAX_RETRIES:
            return False

        if isinstance(exc, ProxyLLMError):
            lowered = exc.message.lower()
            if exc.status_code in {429, 500, 502, 503, 504}:
                return True
            transient_markers = (
                "auth_unavailable",
                "context canceled",
                "server had an error processing your request",
                "internal_server_error",
                "timeout",
                "temporarily unavailable",
            )
            return any(marker in lowered for marker in transient_markers)

        return isinstance(
            exc,
            (
                httpx.TimeoutException,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
                httpx.ReadError,
                httpx.WriteError,
            ),
        )

    @staticmethod
    def _retry_delay(attempt: int) -> float:
        """재시도 지연 계산"""
        return _PROXY_RETRY_BASE_DELAY * (attempt + 1)


class LLMFactory:
    """LLM 제공자별 인스턴스 생성 팩토리"""

    @staticmethod
    def create(provider: str | None = None) -> BaseLLM:
        """설정에 따른 LLM 인스턴스 생성

        Args:
            provider: llm_provider (ollama/claude/codex)
                     None이면 settings.llm_provider 사용

        Returns:
            BaseLLM 구현체 인스턴스

        Raises:
            ValueError: 지원하지 않는 제공자인 경우
        """
        provider = provider or settings.llm_provider

        if provider == "ollama":
            return OllamaLLM()
        elif provider == "claude":
            return ProxyLLM(model=settings.claude_model)
        elif provider == "codex":
            return ProxyLLM(model=settings.codex_model)
        else:
            raise ValueError(
                f"지원하지 않는 LLM 제공자: {provider}. "
                f"지원 가능한 값: ollama, claude, codex"
            )


# 현재 사용할 LLM 인스턴스 (팩토리로 생성)
llm = LLMFactory.create()


def _extract_chat_completion_content(data: dict[str, Any]) -> str:
    """OpenAI 호환 chat.completions 응답에서 텍스트 추출"""
    choices = data.get("choices") or []
    if not choices:
        raise ValueError("프록시 응답에 choices가 없습니다")

    message = choices[0].get("message") or {}
    content = message.get("content")

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts)

    raise ValueError("프록시 응답에서 텍스트를 찾을 수 없습니다")


def _extract_delta_contents(delta: dict[str, Any]) -> list[str]:
    """스트리밍 delta에서 텍스트 조각 추출"""
    content = delta.get("content")
    if isinstance(content, str):
        return [content]
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return parts
    return []


def _extract_proxy_error_message(payload: Any, fallback: str) -> str:
    """OpenAI 호환 에러 payload에서 메시지 추출"""
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        if error:
            return str(error)
    return fallback


def _extract_proxy_error_message_from_bytes(raw: bytes, fallback: str) -> str:
    """바이트 본문에서 프록시 에러 메시지 추출"""
    if not raw:
        return fallback

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        text = raw.decode("utf-8", errors="ignore").strip()
        return text or fallback
    return _extract_proxy_error_message(payload, fallback)


async def get_llm_status() -> dict[str, Any]:
    """현재 LLM 제공자 연결 상태 확인"""
    provider = settings.llm_provider

    if provider == "ollama":
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{settings.ollama_base_url}/api/tags",
                    timeout=10.0,
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as e:
            return {
                "provider": provider,
                "configured_model": settings.llm_model,
                "ok": False,
                "reason": str(e),
            }

        models = [item.get("name", "") for item in payload.get("models", [])]
        return {
            "provider": provider,
            "configured_model": settings.llm_model,
            "ok": True,
            "available_models": models[:20],
            "model_count": len(models),
        }

    configured_model = settings.claude_model if provider == "claude" else settings.codex_model
    if not settings.proxy_api_key.strip():
        return {
            "provider": provider,
            "configured_model": configured_model,
            "ok": False,
            "reason": "PROXY_API_KEY가 설정되지 않았습니다",
        }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.proxy_api_url}/v1/models",
                headers={"Authorization": f"Bearer {settings.proxy_api_key.strip()}"},
                timeout=10.0,
            )
        ProxyLLM._raise_for_status(response)
        payload = response.json()
    except Exception as e:
        return {
            "provider": provider,
            "configured_model": configured_model,
            "ok": False,
            "reason": str(e),
        }

    models = []
    for item in payload.get("data", []):
        if isinstance(item, dict):
            model_name = item.get("id") or item.get("name")
            if isinstance(model_name, str) and model_name:
                models.append(model_name)

    status: dict[str, Any] = {
        "provider": provider,
        "configured_model": configured_model,
        "ok": True,
        "available_models": models[:20],
        "model_count": len(models),
    }
    if configured_model not in models:
        status["warning"] = (
            "프록시 연결은 가능하지만 configured_model이 /v1/models 목록에 없습니다. "
            "프록시 alias 설정 또는 모델명을 확인하세요."
        )
    return status
