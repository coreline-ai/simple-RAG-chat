"""프록시 LLM 테스트"""
import asyncio

import pytest

from app.services.llm import (
    ProxyLLM,
    ProxyLLMError,
    _extract_chat_completion_content,
    _extract_delta_contents,
)


class DummyResponse:
    """httpx.Response 대체 객체"""

    def __init__(self, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text
        self.reason_phrase = "error"

    def json(self):
        return self._json_data


class DummyAsyncClient:
    """httpx.AsyncClient 대체 객체"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


class DelayedDummyAsyncClient(DummyAsyncClient):
    """동시성 검증용 지연 클라이언트"""

    def __init__(self, response, delay=0.05):
        super().__init__(response)
        self.delay = delay
        self.in_flight = 0
        self.max_in_flight = 0

    async def post(self, url, json, headers, timeout):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay)
            return await super().post(url, json, headers, timeout)
        finally:
            self.in_flight -= 1


class SequenceAsyncClient(DummyAsyncClient):
    """호출 순서대로 다른 응답을 반환하는 클라이언트"""

    def __init__(self, responses):
        super().__init__(responses[0])
        self.responses = list(responses)

    async def post(self, url, json, headers, timeout):
        self.calls.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.responses.pop(0)


class DummyStreamingErrorResponse:
    """스트리밍 에러 응답 대체 객체"""

    def __init__(self, status_code=500, body=b'{"error":"auth_unavailable: no auth available"}'):
        self.status_code = status_code
        self.body = body
        self.reason_phrase = "error"

    async def aread(self):
        return self.body

    def json(self):
        raise ValueError("body not preloaded")


@pytest.mark.asyncio
async def test_프록시_generate는_bearer_헤더를_보낸다(monkeypatch):
    response = DummyResponse(
        json_data={
            "choices": [
                {
                    "message": {
                        "content": "응답",
                    }
                }
            ]
        }
    )
    client = DummyAsyncClient(response)
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", lambda: client)

    llm = ProxyLLM(
        model="claude-sonnet-latest",
        proxy_url="http://proxy.test",
        api_key="test-key",
    )
    result = await llm.generate("질문", "컨텍스트")

    assert result == "응답"
    assert client.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert client.calls[0]["url"] == "http://proxy.test/v1/chat/completions"


@pytest.mark.asyncio
async def test_프록시_generate는_api_key_없으면_실패한다():
    llm = ProxyLLM(
        model="claude-sonnet-latest",
        proxy_url="http://proxy.test",
        api_key="",
    )

    with pytest.raises(RuntimeError, match="PROXY_API_KEY"):
        await llm.generate("질문", "컨텍스트")


@pytest.mark.asyncio
async def test_프록시_generate는_동시요청을_직렬화한다(monkeypatch):
    response = DummyResponse(
        json_data={
            "choices": [
                {
                    "message": {
                        "content": "응답",
                    }
                }
            ]
        }
    )
    client = DelayedDummyAsyncClient(response)
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", lambda: client)

    llm = ProxyLLM(
        model="gpt-5-codex",
        proxy_url="http://proxy.test",
        api_key="test-key",
    )

    await asyncio.gather(
        llm.generate("질문1", "컨텍스트"),
        llm.generate("질문2", "컨텍스트"),
    )

    assert client.max_in_flight == 1


@pytest.mark.asyncio
async def test_프록시_generate는_일시적_500을_재시도한다(monkeypatch):
    transient = DummyResponse(
        status_code=500,
        json_data={"error": {"message": "auth_unavailable: no auth available"}},
    )
    success = DummyResponse(
        json_data={
            "choices": [
                {
                    "message": {
                        "content": "재시도 성공",
                    }
                }
            ]
        }
    )
    client = SequenceAsyncClient([transient, success])
    monkeypatch.setattr("app.services.llm.httpx.AsyncClient", lambda: client)

    llm = ProxyLLM(
        model="gpt-5-codex",
        proxy_url="http://proxy.test",
        api_key="test-key",
    )

    result = await llm.generate("질문", "컨텍스트")

    assert result == "재시도 성공"
    assert len(client.calls) == 2


def test_프록시_응답_content_list도_파싱한다():
    data = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "text", "text": "안녕"},
                        {"type": "text", "text": "하세요"},
                    ]
                }
            }
        ]
    }

    assert _extract_chat_completion_content(data) == "안녕하세요"


def test_스트리밍_delta_list도_파싱한다():
    delta = {
        "content": [
            {"type": "text", "text": "반갑"},
            {"type": "text", "text": "습니다"},
        ]
    }

    assert _extract_delta_contents(delta) == ["반갑", "습니다"]


@pytest.mark.asyncio
async def test_스트리밍_에러도_본문을_읽어_메시지를_보존한다():
    response = DummyStreamingErrorResponse()

    with pytest.raises(ProxyLLMError, match="auth_unavailable: no auth available"):
        await ProxyLLM._raise_for_status_async(response)
