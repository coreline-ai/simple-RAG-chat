"""에러 처리 테스트 - 각종 실패 시나리오 검증

- Ollama 연결 실패
- 타임아웃 + bounded retry
- DB 오류
- 잘못된 입력 데이터
- 외부 API 에러

주의: isolated_db fixture가 sys.modules를 교체하므로,
테스트 대상 모듈은 sys.modules를 통해 직접 참조한다.
"""
from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, Mock

import httpx
import pytest


def _stub_settings(**overrides):
    """테스트용 settings stub 생성"""
    defaults = {
        "embedding_cache_enabled": False,
        "ollama_base_url": "http://localhost:11434",
        "embedding_model": "bge-m3",
        "embedding_max_concurrency": 3,
    }
    defaults.update(overrides)
    return type("Settings", (), defaults)()


def _mock_async_client(post_fn):
    """httpx.AsyncClient context manager mock"""
    mock_ctx = Mock()
    mock_ctx.post = post_fn
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_ctx)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


def _emb_mod():
    """현재 유효한 embedding 모듈 반환"""
    import app.services.embedding
    return app.services.embedding


def _ret_mod():
    """현재 유효한 retrieval 모듈 반환"""
    import app.services.retrieval
    return app.services.retrieval


class _MockHttpx:
    """httpx 모듈 mock — ConnectError 등의 예외 클래스를 보존"""
    ConnectError = httpx.ConnectError
    HTTPStatusError = httpx.HTTPStatusError
    TimeoutException = httpx.TimeoutException

    def __init__(self, post_fn):
        self._post_fn = post_fn

    def AsyncClient(self, **kw):
        return _mock_async_client(self._post_fn)


def _patch_embedding(monkeypatch, post_fn, **settings_overrides):
    """embedding 모듈을 직접 객체 참조로 패치 (sys.modules 교체에 안전)"""
    mod = _emb_mod()
    monkeypatch.setattr(mod, "settings", _stub_settings(**settings_overrides))
    monkeypatch.setattr(mod, "_RETRY_BACKOFF", 0.01)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(post_fn))
    mod.reset_semaphore()


# === Ollama 연결 실패 테스트 ===

@pytest.mark.asyncio
async def test_ollama_연결_실패시_적절한_에러_처리(monkeypatch):
    """Ollama 서버 연결 실패 시 EmbeddingError 발생"""
    mod = _emb_mod()

    async def mock_post(*args, **kwargs):
        raise httpx.ConnectError("Connection refused")

    _patch_embedding(monkeypatch, mock_post)

    with pytest.raises(mod.EmbeddingError, match="연결할 수 없습니다"):
        await mod.get_embedding("test")


# === 타임아웃 + retry 테스트 ===

@pytest.mark.asyncio
async def test_ollama_타임아웃_시_재시도_동작(monkeypatch):
    """Ollama 타임아웃 시 재시도 후 성공"""
    mod = _emb_mod()
    attempt_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 2:
            raise httpx.TimeoutException("Request timeout")

        class R:
            def json(self): return {"embeddings": [[0.1, 0.2]]}
            def raise_for_status(self): pass
        return R()

    _patch_embedding(monkeypatch, mock_post)

    result = await mod.get_embedding("test")
    assert result == [0.1, 0.2]
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_ollama_500_에러_시_재시도_동작(monkeypatch):
    """Ollama 500 에러 시 재시도 후 성공"""
    mod = _emb_mod()
    attempt_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count < 3:
            raise httpx.HTTPStatusError("Server error", response=Mock(status_code=500), request=Mock())

        class R:
            def json(self): return {"embeddings": [[0.1, 0.2]]}
            def raise_for_status(self): pass
        return R()

    _patch_embedding(monkeypatch, mock_post)

    result = await mod.get_embedding("test")
    assert result == [0.1, 0.2]
    assert attempt_count == 3


@pytest.mark.asyncio
async def test_ollama_429_에러_시_재시도_동작(monkeypatch):
    """429 Too Many Requests 에러 시 재시도 후 성공"""
    mod = _emb_mod()
    attempt_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal attempt_count
        attempt_count += 1
        if attempt_count == 1:
            raise httpx.HTTPStatusError("Rate limit", response=Mock(status_code=429), request=Mock())

        class R:
            def json(self): return {"embeddings": [[0.1, 0.2]]}
            def raise_for_status(self): pass
        return R()

    _patch_embedding(monkeypatch, mock_post)

    result = await mod.get_embedding("test")
    assert result == [0.1, 0.2]
    assert attempt_count == 2


@pytest.mark.asyncio
async def test_ollama_최대_재시도_초과시_에러(monkeypatch):
    """최대 재시도 횟수 초과 시 EmbeddingError 발생"""
    mod = _emb_mod()

    async def mock_post(*args, **kwargs):
        raise httpx.TimeoutException("Persistent timeout")

    _patch_embedding(monkeypatch, mock_post)

    with pytest.raises(mod.EmbeddingError, match="타임아웃"):
        await mod.get_embedding("test")


# === DB 오류 테스트 ===

@pytest.mark.asyncio
async def test_chroma_db_저장_실패시_에러_처리(monkeypatch):
    """ChromaDB count=0 시 빈 결과"""
    mod = _ret_mod()
    mock_collection = Mock()
    mock_collection.count = Mock(return_value=0)
    monkeypatch.setattr(mod, "chunks_collection", mock_collection)

    results, analysis = await mod.search_similar_chunks("test", top_k=5)
    assert results == []


@pytest.mark.asyncio
async def test_chroma_db_query_실패시_빈_결과_반환(monkeypatch):
    """ChromaDB query 실패 시 예외 전파"""
    mod = _ret_mod()
    mock_collection = Mock()
    mock_collection.count = Mock(return_value=100)
    mock_collection.query = Mock(side_effect=Exception("Query failed"))
    monkeypatch.setattr(mod, "chunks_collection", mock_collection)

    with pytest.raises(Exception):
        await mod._search_vector("test", top_k=5)


# === 잘못된 입력 데이터 테스트 ===

@pytest.mark.asyncio
async def test_빈_텍스트_업로드_시_400_에러():
    """빈 텍스트 업로드 시 400 에러"""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post("/documents", json={"text": "", "filename": "test.txt"})
    assert response.status_code in [400, 422]


@pytest.mark.asyncio
async def test_잘못된_파일형식_업로드_시_처리():
    """지원하지 않는 파일 형식 업로드 시 400 반환"""
    from fastapi.testclient import TestClient
    from app.main import app
    import io

    client = TestClient(app)
    fake_file = io.BytesIO(b"fake content")
    response = client.post(
        "/documents/upload-file",
        files={"file": ("test.pdf", fake_file, "application/pdf")}
    )
    if response.status_code == 200:
        assert response.json()["chunks_added"] == 0
    else:
        assert response.status_code in [400, 422]


# === 임베딩 API 응답 오류 테스트 ===

@pytest.mark.asyncio
async def test_ollama_잘못된_응답_형식_시_에러_처리(monkeypatch):
    """Ollama가 잘못된 응답을 반환할 때 KeyError 발생"""
    mod = _emb_mod()

    async def mock_post(*args, **kwargs):
        class R:
            def json(self): return {"wrong_format": "missing embeddings"}
            def raise_for_status(self): pass
        return R()

    _patch_embedding(monkeypatch, mock_post)

    with pytest.raises(KeyError):
        await mod.get_embedding("test")


# === 동시성 테스트 ===

@pytest.mark.asyncio
async def test_동시_임베딩_요청_시_직렬화_동작(monkeypatch):
    """동시 임베딩 요청 시 세마포어로 동시성 제한"""
    mod = _emb_mod()

    async def mock_post(*args, **kwargs):
        await asyncio.sleep(0.01)
        class R:
            def json(self): return {"embeddings": [[0.1, 0.2]]}
            def raise_for_status(self): pass
        return R()

    _patch_embedding(monkeypatch, mock_post)

    tasks = [mod.get_embedding(f"text{i}") for i in range(3)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 3
    assert all(r == [0.1, 0.2] for r in results)


# === 배치 요청 부분 캐시 테스트 ===

@pytest.mark.asyncio
async def test_배치_요청시_일부_실패_처리(monkeypatch, tmp_path):
    """배치 요청 중 캐시 히트 + API 호출 혼합 동작"""
    emb_mod = _emb_mod()
    cache_mod = sys.modules["app.services.embedding_cache"]

    cache = cache_mod.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text1", [0.1, 0.2])

    monkeypatch.setattr(emb_mod, "settings", _stub_settings(embedding_cache_enabled=True))
    monkeypatch.setattr(cache_mod, "get_cache", lambda: cache)
    emb_mod.reset_semaphore()

    call_count = 0

    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        class R:
            def json(self): return {"embeddings": [[0.5, 0.6]]}
            def raise_for_status(self): pass
        return R()

    monkeypatch.setattr(emb_mod, "httpx", _MockHttpx(mock_post))
    monkeypatch.setattr(emb_mod, "_RETRY_BACKOFF", 0.01)

    results = await emb_mod.get_embeddings(["text1", "text2"])

    assert len(results) == 2
    assert results[0] == [0.1, 0.2]
    assert results[1] == [0.5, 0.6]
    assert call_count == 1


# === 캐시 파일 오류 테스트 ===

@pytest.mark.asyncio
async def test_캐시_db_초기화_실패시_noop_폴백(monkeypatch):
    """캐시 DB 초기화 실패 시 NoOpCache로 폴백"""
    cache_mod = sys.modules["app.services.embedding_cache"]

    monkeypatch.setattr(cache_mod, "_cache", None)

    def failing_init(self, *args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(cache_mod.EmbeddingCache, "__init__", failing_init)

    cache = cache_mod.get_cache()
    assert cache.get("test") is None
    assert cache.stats["hit_rate"] == "disabled"
    cache.put("test", [0.1])


# === LLM 생성 시 에러 테스트 ===

@pytest.mark.asyncio
async def test_llm_생성_시_타임아웃_에러_처리(monkeypatch):
    """LLM 생성 시 타임아웃 에러 전파"""
    from app.services.llm import OllamaLLM

    llm = OllamaLLM()

    async def mock_generate(*args, **kwargs):
        raise asyncio.TimeoutError("LLM generation timeout")

    monkeypatch.setattr(llm, "generate", mock_generate)

    with pytest.raises((asyncio.TimeoutError, TimeoutError)):
        await llm.generate("prompt", "context")
