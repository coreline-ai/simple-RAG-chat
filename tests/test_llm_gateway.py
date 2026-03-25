"""Codex 게이트웨이 라우팅 테스트."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.services.llm import (
    CodexDirectLLM,
    GatewayLLM,
    GatewayTransport,
    PromptLLM,
    parse_codex_auth_payload,
)


def _encode_jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"header.{body}.sig"


class StubPromptLLM(PromptLLM):
    def __init__(self, text: str = "ok", error: Exception | None = None, status: dict | None = None):
        self.text = text
        self.error = error
        self.status = status or {"name": "stub", "ok": True}
        self.generate_calls = 0

    async def generate_full_prompt(self, full_prompt: str) -> str:
        self.generate_calls += 1
        if self.error:
            raise self.error
        return self.text

    async def generate_stream_full_prompt(self, full_prompt: str):
        self.generate_calls += 1
        if self.error:
            raise self.error
        yield self.text

    async def get_transport_status(self) -> dict:
        return self.status


def test_codex_auth_payload는_codex_cli형식을_파싱한다():
    access_token = _encode_jwt(
        {
            "exp": 1_800_000_000,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc-123"},
        }
    )
    payload = {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": access_token,
            "refresh_token": "refresh-123",
        },
    }

    parsed = parse_codex_auth_payload("/tmp/auth.json", payload)

    assert parsed is not None
    assert parsed.source_format == "codex-cli"
    assert parsed.account_id == "acc-123"
    assert parsed.refresh_token == "refresh-123"
    assert parsed.expires_at == 1_800_000_000_000


@pytest.mark.asyncio
async def test_gateway_stable은_proxy실패시_direct로_fallback한다():
    proxy = StubPromptLLM(error=RuntimeError("proxy down"))
    direct = StubPromptLLM(text="direct ok")
    gateway = GatewayLLM(
        provider="codex",
        model="gpt-5-codex",
        routing_mode="stable",
        transports=[
            GatewayTransport(name="proxy", client=proxy, priority=0),
            GatewayTransport(name="direct", client=direct, priority=1),
        ],
    )

    result = await gateway.generate("질문", "컨텍스트")

    assert result == "direct ok"
    assert proxy.generate_calls == 1
    assert direct.generate_calls == 1
    assert gateway.metrics["proxy"].failures == 1
    assert gateway.metrics["direct"].successes == 1


@pytest.mark.asyncio
async def test_gateway_fastest는_누적_latency가_낮은_transport를_우선한다():
    proxy = StubPromptLLM(text="proxy ok")
    direct = StubPromptLLM(text="direct ok")
    gateway = GatewayLLM(
        provider="codex",
        model="gpt-5-codex",
        routing_mode="fastest",
        transports=[
            GatewayTransport(name="proxy", client=proxy, priority=0),
            GatewayTransport(name="direct", client=direct, priority=1),
        ],
    )
    gateway.metrics["proxy"].record_success(2400)
    gateway.metrics["direct"].record_success(900)

    result = await gateway.generate_full_prompt("test prompt")

    assert result == "direct ok"
    assert proxy.generate_calls == 0
    assert direct.generate_calls == 1


@pytest.mark.asyncio
async def test_codex_direct_status는_auth파일만으로_정상여부를_판단한다(tmp_path: Path):
    access_token = _encode_jwt(
        {
            "exp": 1_800_000_000,
            "https://api.openai.com/auth": {"chatgpt_account_id": "acc-999"},
        }
    )
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "tokens": {
                    "access_token": access_token,
                    "refresh_token": "refresh-999",
                    "account_id": "acc-999",
                },
            }
        )
    )

    llm = CodexDirectLLM(
        model="gpt-5-codex",
        auth_path=str(auth_path),
        fallback_auth_path=str(tmp_path / "missing.json"),
    )
    status = await llm.get_transport_status()

    assert status["ok"] is True
    assert status["name"] == "direct"
    assert status["auth_source"] == str(auth_path)
