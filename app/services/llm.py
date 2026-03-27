"""LLM 서비스 및 Codex 라우팅 게이트웨이."""
from __future__ import annotations

import asyncio
import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncIterator

import httpx

from app.config import settings

RAG_PROMPT_TEMPLATE = """다음은 채팅 로그에서 검색된 관련 내용입니다.
이 내용을 참고하여 사용자의 질문에 한글로 정확하게 답변해주세요.
검색된 내용에 없는 정보는 추측하지 마세요.
특히 전체 목록/전체 인원 질문은 컨텍스트에 명시된 대상만 답하고,
전수 여부가 불명확하면 일부만 확인된 것이라고 밝혀주세요.

=== 검색된 컨텍스트 ===
{context}
========================

질문: {prompt}

답변:"""

_PROXY_MAX_RETRIES = 2
_PROXY_RETRY_BASE_DELAY = 0.75
_CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
_GATEWAY_WARMUP_PROMPT = "Reply with exactly: warmup ok"

_proxy_request_lock: asyncio.Lock | None = None
_codex_refresh_lock: asyncio.Lock | None = None


def _get_proxy_request_lock() -> asyncio.Lock:
    global _proxy_request_lock
    if _proxy_request_lock is None:
        _proxy_request_lock = asyncio.Lock()
    return _proxy_request_lock


def _get_codex_refresh_lock() -> asyncio.Lock:
    global _codex_refresh_lock
    if _codex_refresh_lock is None:
        _codex_refresh_lock = asyncio.Lock()
    return _codex_refresh_lock


def reset_llm_locks() -> None:
    """asyncio Lock을 리셋 (테스트 간 이벤트 루프 전환 시 호출)"""
    global _proxy_request_lock, _codex_refresh_lock
    _proxy_request_lock = None
    _codex_refresh_lock = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _maybe_isoformat(timestamp_ms: float | None) -> str | None:
    if not timestamp_ms:
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def _safe_metric_value(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


class ProxyLLMError(RuntimeError):
    """프록시/직접 호출 실패를 표현하는 예외."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"프록시 LLM 호출 실패 ({status_code}): {message}")


@dataclass
class CodexStoredTokens:
    source_path: str
    source_format: str
    access_token: str
    refresh_token: str
    account_id: str | None = None
    expires_at: int | None = None
    id_token: str | None = None


@dataclass
class TransportMetrics:
    name: str
    successes: int = 0
    failures: int = 0
    total_ms_samples: list[float] = field(default_factory=list)
    ttfb_ms_samples: list[float] = field(default_factory=list)
    last_total_ms: float | None = None
    last_ttfb_ms: float | None = None
    last_ok_at: str | None = None
    last_error: str | None = None

    def record_success(self, total_ms: float, ttfb_ms: float | None = None) -> None:
        self.successes += 1
        self.last_total_ms = total_ms
        self.last_ttfb_ms = ttfb_ms
        self.last_ok_at = _utc_now_iso()
        self.last_error = None
        self.total_ms_samples = (self.total_ms_samples + [total_ms])[-10:]
        if ttfb_ms is not None:
            self.ttfb_ms_samples = (self.ttfb_ms_samples + [ttfb_ms])[-10:]

    def record_failure(self, error: Exception) -> None:
        self.failures += 1
        self.last_error = str(error)

    @property
    def avg_total_ms(self) -> float | None:
        if not self.total_ms_samples:
            return None
        return sum(self.total_ms_samples) / len(self.total_ms_samples)

    @property
    def avg_ttfb_ms(self) -> float | None:
        if not self.ttfb_ms_samples:
            return None
        return sum(self.ttfb_ms_samples) / len(self.ttfb_ms_samples)

    def as_dict(self) -> dict[str, Any]:
        return {
            "successes": self.successes,
            "failures": self.failures,
            "avg_total_ms": _safe_metric_value(self.avg_total_ms),
            "avg_ttfb_ms": _safe_metric_value(self.avg_ttfb_ms),
            "last_total_ms": _safe_metric_value(self.last_total_ms),
            "last_ttfb_ms": _safe_metric_value(self.last_ttfb_ms),
            "last_ok_at": self.last_ok_at,
            "last_error": self.last_error,
        }


@dataclass
class GatewayTransport:
    name: str
    client: "PromptLLM"
    priority: int


class BaseLLM(ABC):
    @abstractmethod
    async def generate(self, prompt: str, context: str) -> str:
        ...

    @abstractmethod
    async def generate_stream(self, prompt: str, context: str) -> AsyncIterator[str]:
        ...


class PromptLLM(BaseLLM):
    """RAG 프롬프트 조립과 transport 호출을 분리하는 기본 클래스."""

    async def generate(self, prompt: str, context: str) -> str:
        return await self.generate_full_prompt(
            RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)
        )

    async def generate_stream(self, prompt: str, context: str) -> AsyncIterator[str]:
        async for token in self.generate_stream_full_prompt(
            RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)
        ):
            yield token

    @abstractmethod
    async def generate_full_prompt(self, full_prompt: str) -> str:
        ...

    @abstractmethod
    async def generate_stream_full_prompt(self, full_prompt: str) -> AsyncIterator[str]:
        ...

    async def get_transport_status(self) -> dict[str, Any]:
        return {
            "name": getattr(self, "transport_name", self.__class__.__name__.lower()),
            "ok": True,
        }


class OllamaLLM(PromptLLM):
    """Ollama 기반 LLM 구현체."""

    transport_name = "ollama"

    def __init__(self, model: str | None = None):
        self.model = model or settings.llm_model
        self.base_url = settings.ollama_base_url

    async def generate_full_prompt(self, full_prompt: str) -> str:
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

    async def generate_stream_full_prompt(self, full_prompt: str) -> AsyncIterator[str]:
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

    async def get_transport_status(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/tags", timeout=10.0)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            return {
                "name": self.transport_name,
                "ok": False,
                "reason": str(exc),
                "model": self.model,
            }

        models = [item.get("name", "") for item in payload.get("models", [])]
        return {
            "name": self.transport_name,
            "ok": True,
            "model": self.model,
            "available_models": models[:20],
            "model_count": len(models),
        }


class ProxyLLM(PromptLLM):
    """OpenAI 호환 프록시 transport."""

    transport_name = "proxy"

    def __init__(
        self,
        model: str | None = None,
        proxy_url: str | None = None,
        api_key: str | None = None,
        system_prompt: str = "채팅 로그 기반 RAG 시스템입니다.",
    ):
        self.model = model or settings.claude_model
        self.proxy_url = proxy_url or settings.proxy_api_url
        self.api_key = api_key if api_key is not None else settings.proxy_api_key
        self.system_prompt = system_prompt
        self.endpoint = f"{self.proxy_url}/v1/chat/completions"

    async def generate_full_prompt(self, full_prompt: str) -> str:
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
                        return _extract_chat_completion_content(response.json())
                except (ProxyLLMError, httpx.HTTPError) as exc:
                    if not self._should_retry(exc, attempt):
                        raise
                    await asyncio.sleep(self._retry_delay(attempt))
        raise RuntimeError("unreachable")

    async def generate_stream_full_prompt(self, full_prompt: str) -> AsyncIterator[str]:
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
                                if not line.strip() or not line.startswith("data: "):
                                    continue
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    return
                                data = json.loads(data_str)
                                if "choices" not in data or not data["choices"]:
                                    continue
                                delta = data["choices"][0].get("delta", {})
                                for chunk in _extract_delta_contents(delta):
                                    emitted_any = True
                                    yield chunk
                            return
                except (ProxyLLMError, httpx.HTTPError) as exc:
                    if emitted_any or not self._should_retry(exc, attempt):
                        raise
                    await asyncio.sleep(self._retry_delay(attempt))

    async def get_transport_status(self) -> dict[str, Any]:
        if not self.api_key.strip():
            return {
                "name": self.transport_name,
                "ok": False,
                "model": self.model,
                "reason": "PROXY_API_KEY가 설정되지 않았습니다",
            }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.proxy_url}/v1/models",
                    headers=self._build_headers(),
                    timeout=10.0,
                )
            self._raise_for_status(response)
            payload = response.json()
        except Exception as exc:
            return {
                "name": self.transport_name,
                "ok": False,
                "model": self.model,
                "reason": str(exc),
            }

        models = []
        for item in payload.get("data", []):
            if isinstance(item, dict):
                model_name = item.get("id") or item.get("name")
                if isinstance(model_name, str) and model_name:
                    models.append(model_name)

        status = {
            "name": self.transport_name,
            "ok": True,
            "model": self.model,
            "available_models": models[:20],
            "model_count": len(models),
        }
        if self.model not in models:
            status["warning"] = (
                "프록시 연결은 가능하지만 configured_model이 /v1/models 목록에 없습니다. "
                "프록시 alias 설정 또는 모델명을 확인하세요."
            )
        return status

    def _build_payload(self, full_prompt: str, *, stream: bool) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": full_prompt},
            ],
            "stream": stream,
        }

    def _build_headers(self) -> dict[str, str]:
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
        return _PROXY_RETRY_BASE_DELAY * (attempt + 1)


class CodexDirectLLM(PromptLLM):
    """ChatGPT backend Codex direct transport."""

    transport_name = "direct"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        auth_path: str | None = None,
        fallback_auth_path: str | None = None,
        system_prompt: str = "채팅 로그 기반 RAG 시스템입니다.",
    ):
        self.model = model or settings.codex_model
        self.base_url = (base_url or settings.codex_direct_base_url).rstrip("/")
        self.auth_path = Path(auth_path or settings.codex_auth_path).expanduser()
        self.fallback_auth_path = Path(
            fallback_auth_path or settings.codex_fallback_auth_path
        ).expanduser()
        self.system_prompt = system_prompt

    async def generate_full_prompt(self, full_prompt: str) -> str:
        text, _ = await self._collect_response(full_prompt)
        return text

    async def generate_stream_full_prompt(self, full_prompt: str) -> AsyncIterator[str]:
        tokens = await get_valid_codex_tokens(self.auth_path, self.fallback_auth_path)
        if not tokens:
            raise RuntimeError("Codex direct auth를 찾을 수 없습니다")
        if not tokens.account_id:
            raise RuntimeError("Codex direct account_id를 찾을 수 없습니다")

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/codex/responses",
                headers=self._build_headers(tokens),
                json=self._build_request_body(full_prompt),
            ) as response:
                await ProxyLLM._raise_for_status_async(response)
                emitted_any = False
                final_response: dict[str, Any] | None = None
                async for data_str in _iter_sse_data_strings(response):
                    if data_str == "[DONE]":
                        break
                    parsed = json.loads(data_str)
                    event_type = parsed.get("type")
                    if (
                        event_type == "response.output_text.delta"
                        and isinstance(parsed.get("delta"), str)
                    ):
                        emitted_any = True
                        yield parsed["delta"]
                    if (
                        event_type in {"response.done", "response.completed"}
                        and isinstance(parsed.get("response"), dict)
                    ):
                        final_response = parsed["response"]
                if not emitted_any and final_response is not None:
                    final_text = _extract_codex_response_text(final_response)
                    if final_text:
                        yield final_text

    async def get_transport_status(self) -> dict[str, Any]:
        try:
            tokens = await get_valid_codex_tokens(self.auth_path, self.fallback_auth_path)
        except Exception as exc:
            return {
                "name": self.transport_name,
                "ok": False,
                "model": self.model,
                "reason": str(exc),
            }

        if not tokens:
            return {
                "name": self.transport_name,
                "ok": False,
                "model": self.model,
                "reason": "Codex auth 파일을 찾지 못했습니다",
            }
        if not tokens.account_id:
            return {
                "name": self.transport_name,
                "ok": False,
                "model": self.model,
                "reason": "Codex account_id가 없습니다",
            }

        return {
            "name": self.transport_name,
            "ok": True,
            "model": self.model,
            "auth_source": tokens.source_path,
            "auth_format": tokens.source_format,
            "expires_at": _maybe_isoformat(tokens.expires_at),
            "probe": "auth",
        }

    async def _collect_response(self, full_prompt: str) -> tuple[str, dict[str, Any] | None]:
        tokens = await get_valid_codex_tokens(self.auth_path, self.fallback_auth_path)
        if not tokens:
            raise RuntimeError("Codex direct auth를 찾을 수 없습니다")
        if not tokens.account_id:
            raise RuntimeError("Codex direct account_id를 찾을 수 없습니다")

        final_response: dict[str, Any] | None = None
        accumulated: list[str] = []

        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/codex/responses",
                headers=self._build_headers(tokens),
                json=self._build_request_body(full_prompt),
            ) as response:
                await ProxyLLM._raise_for_status_async(response)
                async for data_str in _iter_sse_data_strings(response):
                    if data_str == "[DONE]":
                        break
                    parsed = json.loads(data_str)
                    event_type = parsed.get("type")
                    if (
                        event_type == "response.output_text.delta"
                        and isinstance(parsed.get("delta"), str)
                    ):
                        accumulated.append(parsed["delta"])
                    if (
                        event_type in {"response.done", "response.completed"}
                        and isinstance(parsed.get("response"), dict)
                    ):
                        final_response = parsed["response"]

        text = "".join(accumulated).strip()
        if not text and final_response is not None:
            text = _extract_codex_response_text(final_response)
        return text, final_response

    def _build_headers(self, tokens: CodexStoredTokens) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tokens.access_token}",
            "chatgpt-account-id": tokens.account_id or "",
            "OpenAI-Beta": "responses=experimental",
            "originator": "codex_cli_rs",
        }

    def _build_request_body(self, full_prompt: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": full_prompt}],
                }
            ],
            "stream": True,
            "store": False,
            "reasoning": {"effort": "medium", "summary": "auto"},
            "text": {"verbosity": "medium"},
        }


class GatewayLLM(PromptLLM):
    """여러 transport를 라우팅하는 로컬 게이트웨이."""

    transport_name = "gateway"

    def __init__(
        self,
        provider: str,
        model: str,
        routing_mode: str,
        transports: list[GatewayTransport],
    ):
        self.provider = provider
        self.model = model
        self.routing_mode = routing_mode
        self.transports = transports
        self.metrics = {
            transport.name: TransportMetrics(name=transport.name)
            for transport in transports
        }
        self._warmup_lock = asyncio.Lock()

    async def generate_full_prompt(self, full_prompt: str) -> str:
        last_error: Exception | None = None
        for transport in self._ordered_transports():
            started = perf_counter()
            try:
                result = await transport.client.generate_full_prompt(full_prompt)
            except Exception as exc:
                self.metrics[transport.name].record_failure(exc)
                last_error = exc
                continue

            total_ms = (perf_counter() - started) * 1000
            self.metrics[transport.name].record_success(total_ms)
            return result

        if last_error:
            raise last_error
        raise RuntimeError("사용 가능한 LLM transport가 없습니다")

    async def generate_stream_full_prompt(self, full_prompt: str) -> AsyncIterator[str]:
        last_error: Exception | None = None
        for transport in self._ordered_transports():
            started = perf_counter()
            first_token_ms: float | None = None
            emitted_any = False
            try:
                async for token in transport.client.generate_stream_full_prompt(full_prompt):
                    if first_token_ms is None:
                        first_token_ms = (perf_counter() - started) * 1000
                    emitted_any = True
                    yield token
                total_ms = (perf_counter() - started) * 1000
                self.metrics[transport.name].record_success(total_ms, first_token_ms)
                return
            except Exception as exc:
                self.metrics[transport.name].record_failure(exc)
                last_error = exc
                if emitted_any:
                    raise
                continue

        if last_error:
            raise last_error
        raise RuntimeError("사용 가능한 LLM transport가 없습니다")

    async def get_transport_status(self) -> dict[str, Any]:
        statuses = []
        ok = False
        for transport in self.transports:
            status = await transport.client.get_transport_status()
            status["metrics"] = self.metrics[transport.name].as_dict()
            status["priority"] = transport.priority
            statuses.append(status)
            ok = ok or bool(status.get("ok"))

        selected = self._select_transport_name(
            [status for status in statuses if status.get("ok")]
        )
        result: dict[str, Any] = {
            "provider": self.provider,
            "configured_model": self.model,
            "routing_mode": self.routing_mode,
            "ok": ok,
            "selected_transport": selected,
            "transports": statuses,
        }
        if self.routing_mode == "fastest" and all(
            self.metrics[transport.name].avg_total_ms is None for transport in self.transports
        ):
            result["note"] = (
                "fastest 모드이지만 아직 latency 샘플이 없습니다. "
                "첫 요청 전까지는 stable 순서로 동작합니다."
            )
        return result

    async def warmup(self) -> dict[str, Any]:
        async with self._warmup_lock:
            results = []
            for transport in self._ordered_transports():
                started = perf_counter()
                try:
                    text = await transport.client.generate_full_prompt(_GATEWAY_WARMUP_PROMPT)
                except Exception as exc:
                    self.metrics[transport.name].record_failure(exc)
                    results.append(
                        {
                            "name": transport.name,
                            "ok": False,
                            "reason": str(exc),
                        }
                    )
                    continue

                total_ms = (perf_counter() - started) * 1000
                self.metrics[transport.name].record_success(total_ms)
                results.append(
                    {
                        "name": transport.name,
                        "ok": text.strip().lower().endswith("warmup ok"),
                        "latency_ms": _safe_metric_value(total_ms),
                    }
                )

            return {
                "provider": self.provider,
                "routing_mode": self.routing_mode,
                "results": results,
            }

    def _ordered_transports(self) -> list[GatewayTransport]:
        filtered = list(self.transports)
        if self.routing_mode == "proxy_only":
            filtered = [item for item in filtered if item.name == "proxy"]
        elif self.routing_mode == "direct_only":
            filtered = [item for item in filtered if item.name == "direct"]

        if self.routing_mode != "fastest":
            return sorted(filtered, key=lambda item: item.priority)

        return sorted(
            filtered,
            key=lambda item: (
                self._transport_score(item.name),
                item.priority,
            ),
        )

    def _transport_score(self, name: str) -> float:
        avg = self.metrics[name].avg_total_ms
        if avg is None:
            return 1_000_000
        return avg

    def _select_transport_name(self, healthy_statuses: list[dict[str, Any]]) -> str | None:
        healthy_names = {status["name"] for status in healthy_statuses}
        for transport in self._ordered_transports():
            if transport.name in healthy_names:
                return transport.name
        return None


def _extract_chat_completion_content(data: dict[str, Any]) -> str:
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
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return error.get("message") or str(error)
        if error:
            return str(error)
    return fallback


def _extract_proxy_error_message_from_bytes(raw: bytes, fallback: str) -> str:
    if not raw:
        return fallback

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        text = raw.decode("utf-8", errors="ignore").strip()
        return text or fallback
    return _extract_proxy_error_message(payload, fallback)


def _decode_jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) != 3 or not parts[1]:
        return None

    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("utf-8"))
        return json.loads(decoded)
    except Exception:
        return None


def _extract_account_id_from_access_token(access_token: str) -> str | None:
    payload = _decode_jwt_payload(access_token)
    auth_claim = payload.get("https://api.openai.com/auth") if payload else None
    if isinstance(auth_claim, dict):
        account_id = auth_claim.get("chatgpt_account_id")
        if isinstance(account_id, str) and account_id:
            return account_id
    return None


def _extract_jwt_expiry(access_token: str) -> int | None:
    payload = _decode_jwt_payload(access_token)
    exp = payload.get("exp") if payload else None
    if isinstance(exp, (int, float)):
        return int(exp * 1000)
    return None


def parse_codex_auth_payload(source_path: str, raw: Any) -> CodexStoredTokens | None:
    if not isinstance(raw, dict):
        return None

    cli_tokens = raw.get("tokens")
    if (
        isinstance(cli_tokens, dict)
        and isinstance(cli_tokens.get("access_token"), str)
        and isinstance(cli_tokens.get("refresh_token"), str)
    ):
        access_token = cli_tokens["access_token"]
        return CodexStoredTokens(
            source_path=source_path,
            source_format="codex-cli",
            access_token=access_token,
            refresh_token=cli_tokens["refresh_token"],
            account_id=(
                cli_tokens.get("account_id")
                if isinstance(cli_tokens.get("account_id"), str)
                else _extract_account_id_from_access_token(access_token)
            ),
            expires_at=_extract_jwt_expiry(access_token),
            id_token=cli_tokens.get("id_token")
            if isinstance(cli_tokens.get("id_token"), str)
            else None,
        )

    if isinstance(raw.get("access_token"), str) and isinstance(raw.get("refresh_token"), str):
        access_token = raw["access_token"]
        return CodexStoredTokens(
            source_path=source_path,
            source_format="proxy",
            access_token=access_token,
            refresh_token=raw["refresh_token"],
            account_id=(
                raw.get("chatgpt_account_id")
                if isinstance(raw.get("chatgpt_account_id"), str)
                else _extract_account_id_from_access_token(access_token)
            ),
            expires_at=(
                raw.get("expires_at")
                if isinstance(raw.get("expires_at"), int)
                else _extract_jwt_expiry(access_token)
            ),
        )

    return None


def should_refresh_codex_token(tokens: CodexStoredTokens, now_ms: int | None = None) -> bool:
    if tokens.expires_at is None:
        return False
    now_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
    return now_ms >= tokens.expires_at - 5 * 60 * 1000


async def load_codex_tokens(
    primary_path: Path,
    fallback_path: Path,
) -> CodexStoredTokens | None:
    for file_path in (primary_path, fallback_path):
        if not file_path.exists():
            continue
        try:
            raw = json.loads(file_path.read_text())
        except Exception:
            continue
        parsed = parse_codex_auth_payload(str(file_path), raw)
        if parsed:
            return parsed
    return None


async def refresh_codex_tokens(tokens: CodexStoredTokens) -> CodexStoredTokens:
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            _CODEX_OAUTH_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": tokens.refresh_token,
                "client_id": _CODEX_OAUTH_CLIENT_ID,
            },
        )
    response.raise_for_status()
    payload = response.json()

    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    if not isinstance(access_token, str) or not isinstance(refresh_token, str):
        raise RuntimeError("Codex auth refresh 응답이 올바르지 않습니다")

    refreshed = CodexStoredTokens(
        source_path=tokens.source_path,
        source_format=tokens.source_format,
        access_token=access_token,
        refresh_token=refresh_token,
        account_id=_extract_account_id_from_access_token(access_token) or tokens.account_id,
        expires_at=(
            int(datetime.now(timezone.utc).timestamp() * 1000 + payload["expires_in"] * 1000)
            if isinstance(payload.get("expires_in"), (int, float))
            else _extract_jwt_expiry(access_token)
        ),
        id_token=payload.get("id_token") if isinstance(payload.get("id_token"), str) else tokens.id_token,
    )
    _persist_codex_tokens(refreshed)
    return refreshed


def _persist_codex_tokens(tokens: CodexStoredTokens) -> None:
    path = Path(tokens.source_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if tokens.source_format == "codex-cli":
        payload = {
            "auth_mode": "chatgpt",
            "OPENAI_API_KEY": None,
            "tokens": {
                "id_token": tokens.id_token,
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "account_id": tokens.account_id,
            },
            "last_refresh": _utc_now_iso(),
        }
    else:
        payload = {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "expires_at": tokens.expires_at,
            "chatgpt_account_id": tokens.account_id,
        }
    path.write_text(f"{json.dumps(payload, indent=2)}\n")
    path.chmod(0o600)


async def get_valid_codex_tokens(
    primary_path: Path,
    fallback_path: Path,
) -> CodexStoredTokens | None:
    tokens = await load_codex_tokens(primary_path, fallback_path)
    if not tokens:
        return None
    if not should_refresh_codex_token(tokens):
        return tokens

    async with _get_codex_refresh_lock():
        latest = await load_codex_tokens(primary_path, fallback_path)
        if latest and not should_refresh_codex_token(latest):
            return latest
        return await refresh_codex_tokens(latest or tokens)


def _extract_codex_response_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if (
                isinstance(content, dict)
                and content.get("type") == "output_text"
                and isinstance(content.get("text"), str)
            ):
                parts.append(content["text"])
    return "".join(parts)


async def _iter_sse_data_strings(response: httpx.Response) -> AsyncIterator[str]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue
        if line.startswith("data: "):
            data_lines.append(line[6:])
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        yield "\n".join(data_lines)


class LLMFactory:
    """LLM 제공자별 인스턴스 생성 팩토리."""

    @staticmethod
    def create(provider: str | None = None) -> BaseLLM:
        provider = provider or settings.llm_provider

        if provider == "ollama":
            return OllamaLLM()
        if provider == "claude":
            return ProxyLLM(model=settings.claude_model)
        if provider == "codex":
            transports: list[GatewayTransport] = []
            if settings.codex_proxy_enabled:
                transports.append(
                    GatewayTransport(
                        name="proxy",
                        client=ProxyLLM(model=settings.codex_model),
                        priority=0,
                    )
                )
            if settings.codex_direct_enabled:
                transports.append(
                    GatewayTransport(
                        name="direct",
                        client=CodexDirectLLM(model=settings.codex_model),
                        priority=1,
                    )
                )
            if not transports:
                raise ValueError("codex용 transport가 모두 비활성화되어 있습니다")
            return GatewayLLM(
                provider="codex",
                model=settings.codex_model,
                routing_mode=settings.llm_routing_mode,
                transports=transports,
            )

        raise ValueError(
            f"지원하지 않는 LLM 제공자: {provider}. "
            f"지원 가능한 값: ollama, claude, codex"
        )


llm = LLMFactory.create()


async def initialize_llm_runtime() -> dict[str, Any] | None:
    if not isinstance(llm, GatewayLLM):
        return None
    if not (settings.llm_warmup_on_startup or settings.llm_selftest_on_startup):
        return None
    return await llm.warmup()


async def get_llm_status() -> dict[str, Any]:
    if settings.llm_provider == "ollama":
        return {
            "provider": "ollama",
            "configured_model": settings.llm_model,
            **await OllamaLLM(model=settings.llm_model).get_transport_status(),
        }

    if isinstance(llm, GatewayLLM):
        return await llm.get_transport_status()

    if isinstance(llm, PromptLLM):
        status = await llm.get_transport_status()
        return {
            "provider": settings.llm_provider,
            "configured_model": (
                settings.claude_model
                if settings.llm_provider == "claude"
                else settings.codex_model
            ),
            **status,
        }

    return {
        "provider": settings.llm_provider,
        "configured_model": settings.llm_model,
        "ok": False,
        "reason": "LLM 상태를 확인할 수 없습니다",
    }
