"""임베딩 서비스 단위 테스트 - 캐시 hit/miss 동작 검증

주의: isolated_db fixture가 sys.modules를 교체하므로,
테스트 대상 모듈은 import 문으로 현재 모듈을 참조한다.
"""
from __future__ import annotations

import pytest


# === 더미 임베딩 값 ===

_DUMMY_EMBEDDING = [0.1, 0.2, 0.3, 0.4]
_DUMMY_EMBEDDING_2 = [0.5, 0.6, 0.7, 0.8]


# === Mock AsyncClient Factory ===

class _MockBatchResponse:
    """배치 임베딩 응답 mock"""
    def __init__(self, embeddings):
        self._embeddings = embeddings

    def json(self):
        return {"embeddings": self._embeddings}

    def raise_for_status(self):
        pass


class _MockAsyncContextManager:
    """httpx.AsyncClient mock"""
    def __init__(self, post_func=None):
        self._post_func = post_func

    async def post(self, url, json=None, **kwargs):
        if self._post_func:
            return await self._post_func(url, json, **kwargs)
        class _MockResponse:
            def json(self):
                return {"embeddings": [[_DUMMY_EMBEDDING]]}
            def raise_for_status(self):
                pass
        return _MockResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _emb():
    """현재 유효한 embedding 모듈"""
    import app.services.embedding
    return app.services.embedding


def _cache_mod():
    """현재 유효한 embedding_cache 모듈 (sys.modules 직접 참조)"""
    import sys
    return sys.modules["app.services.embedding_cache"]


class _MockHttpx:
    """httpx 모듈 mock — AsyncClient를 올바르게 반환"""
    ConnectError = Exception
    HTTPStatusError = Exception
    TimeoutException = Exception

    def __init__(self, mock_ctx):
        self._mock_ctx = mock_ctx

    def AsyncClient(self, **kw):
        return self._mock_ctx


# === P1-1: get_embedding 단일 요청 테스트 ===

@pytest.mark.asyncio
async def test_get_embedding은_캐시_미스시_ollama를_호출한다(monkeypatch, tmp_path):
    """캐시가 없을 때 Ollama API를 호출하고 결과를 캐시에 저장"""
    mod = _emb()
    monkeypatch.setattr(mod.settings, "embedding_cache_enabled", False)

    post_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal post_called
        post_called = True
        class MockResponse:
            def json(self):
                return {"embeddings": [_DUMMY_EMBEDDING]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(mock_ctx))

    result = await mod.get_embedding("test")

    assert result == _DUMMY_EMBEDDING
    assert post_called


@pytest.mark.asyncio
async def test_get_embedding은_캐시_히트시_ollama를_호출하지_않는다(monkeypatch, tmp_path):
    """캐시에 있으면 Ollama API를 호출하지 않음"""
    mod = _emb()
    cm = _cache_mod()
    cache = cm.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("test", _DUMMY_EMBEDDING)

    monkeypatch.setattr(mod.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(cm, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        raise RuntimeError("API should not be called")

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(mock_ctx))

    result = await mod.get_embedding("test")

    assert result == _DUMMY_EMBEDDING
    assert not api_called


# === P1-2: get_embeddings 배치 요청 테스트 ===

@pytest.mark.asyncio
async def test_get_embeddings_전체_캐시_히트시_api를_호출하지_않는다(monkeypatch, tmp_path):
    """모든 텍스트가 캐시에 있으면 API를 호출하지 않음"""
    mod = _emb()
    cm = _cache_mod()
    cache = cm.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text1", _DUMMY_EMBEDDING)
    cache.put("text2", _DUMMY_EMBEDDING_2)

    monkeypatch.setattr(mod.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(cm, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        raise RuntimeError("API should not be called")

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(mock_ctx))

    results = await mod.get_embeddings(["text1", "text2"])

    assert len(results) == 2
    assert results[0] == _DUMMY_EMBEDDING
    assert results[1] == _DUMMY_EMBEDDING_2
    assert not api_called


@pytest.mark.asyncio
async def test_get_embeddings_부분_캐시_히트시_미스_건만_api를_호출한다(monkeypatch, tmp_path):
    """일부만 캐시에 있으면 미스 건만 API 호출"""
    mod = _emb()
    cm = _cache_mod()
    cache = cm.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text1", _DUMMY_EMBEDDING)

    monkeypatch.setattr(mod.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(cm, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        input_val = json.get("input", "")
        if isinstance(input_val, list):
            return _MockBatchResponse([_DUMMY_EMBEDDING_2 for _ in input_val])
        class MockResponse:
            def json(self):
                return {"embeddings": [[_DUMMY_EMBEDDING_2]]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(mock_ctx))

    results = await mod.get_embeddings(["text1", "text2"])

    assert len(results) == 2
    assert results[0] == _DUMMY_EMBEDDING
    assert results[1] == _DUMMY_EMBEDDING_2
    assert api_called


@pytest.mark.asyncio
async def test_get_embeddings_결과_순서를_보존한다(monkeypatch, tmp_path):
    """배치 요청 결과의 순서가 입력 순서와 일치"""
    mod = _emb()
    cm = _cache_mod()
    cache = cm.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text2", _DUMMY_EMBEDDING_2)

    monkeypatch.setattr(mod.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(cm, "get_cache", lambda: cache)

    async def mock_post(url, json, **kwargs):
        input_val = json.get("input", "")
        if isinstance(input_val, list):
            return _MockBatchResponse([_DUMMY_EMBEDDING for _ in input_val])
        class MockResponse:
            def json(self):
                return {"embeddings": [[_DUMMY_EMBEDDING]]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr(mod, "httpx", _MockHttpx(mock_ctx))

    results = await mod.get_embeddings(["text1", "text2", "text3"])

    assert len(results) == 3
    assert results[0] == _DUMMY_EMBEDDING
    assert results[1] == _DUMMY_EMBEDDING_2


# === P1-3: EmbeddingCache 클래스 테스트 ===

class TestEmbeddingCache:
    """임베딩 캐시 클래스 테스트"""

    def test_get_put_기본_동작(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        assert cache.get("test") is None
        cache.put("test", _DUMMY_EMBEDDING)
        assert cache.get("test") == _DUMMY_EMBEDDING

    def test_get_batch_배치_조회(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        cache.put("text1", _DUMMY_EMBEDDING)
        cache.put("text3", _DUMMY_EMBEDDING_2)
        hits = cache.get_batch(["text1", "text2", "text3"])
        assert hits == {0: _DUMMY_EMBEDDING, 2: _DUMMY_EMBEDDING_2}
        assert 1 not in hits

    def test_put_batch_배치_저장(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        cache.put_batch(["text1", "text2"], [_DUMMY_EMBEDDING, _DUMMY_EMBEDDING_2])
        assert cache.get("text1") == _DUMMY_EMBEDDING
        assert cache.get("text2") == _DUMMY_EMBEDDING_2

    def test_stats_히트_률_계산(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        cache.get("test1")
        cache.get("test2")
        cache.put("test1", _DUMMY_EMBEDDING)
        cache.get("test1")
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["hit_rate"] == "33.3%"

    def test_clear_캐시_초기화(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        cache.put("test", _DUMMY_EMBEDDING)
        cache.clear()
        assert cache.get("test") is None
        assert cache.count() == 0

    def test_count_항목_수_반환(self, tmp_path):
        cache = _cache_mod().EmbeddingCache(db_path=tmp_path / "test.db")
        assert cache.count() == 0
        cache.put("test1", _DUMMY_EMBEDDING)
        assert cache.count() == 1
        cache.put("test2", _DUMMY_EMBEDDING_2)
        assert cache.count() == 2
