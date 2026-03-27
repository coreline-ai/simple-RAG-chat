"""임베딩 서비스 단위 테스트 - 캐시 hit/miss 동작 검증"""
from __future__ import annotations

import pytest

from app.services import embedding, embedding_cache


# === 더미 임베딩 값 ===

_DUMMY_EMBEDDING = [0.1, 0.2, 0.3, 0.4]
_DUMMY_EMBEDDING_2 = [0.5, 0.6, 0.7, 0.8]


# === Mock AsyncClient Factory ===

class _MockBatchResponse:
    """배치 임베딩 응답 mock - API 응답 형식과 일치"""
    def __init__(self, embeddings):
        # embeddings: list[float]의 리스트
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
                # 단일 요청: [[emb]], 배치: [[emb1], [emb2], ...]
                return {"embeddings": [[_DUMMY_EMBEDDING]]}
            def raise_for_status(self):
                pass
        return _MockResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


# === P1-1: get_embedding 단일 요청 테스트 ===

@pytest.mark.asyncio
async def test_get_embedding은_캐시_미스시_ollama를_호출한다(monkeypatch, tmp_path):
    """캐시가 없을 때 Ollama API를 호출하고 결과를 캐시에 저장"""
    # 캐시 비활성화 상태에서 테스트
    monkeypatch.setattr(embedding.settings, "embedding_cache_enabled", False)

    post_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal post_called
        post_called = True
        class MockResponse:
            def json(self):
                # 단일 요청: [vector]
                return {"embeddings": [_DUMMY_EMBEDDING]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", lambda **kw: mock_ctx)

    result = await embedding.get_embedding("test")

    assert result == _DUMMY_EMBEDDING
    assert post_called


@pytest.mark.asyncio
async def test_get_embedding은_캐시_히트시_ollama를_호출하지_않는다(monkeypatch, tmp_path):
    """캐시에 있으면 Ollama API를 호출하지 않음"""
    cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("test", _DUMMY_EMBEDDING)

    # 캐시 활성화
    monkeypatch.setattr(embedding.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(embedding_cache, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        raise RuntimeError("API should not be called")

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", lambda **kw: mock_ctx)

    result = await embedding.get_embedding("test")

    assert result == _DUMMY_EMBEDDING
    assert not api_called  # API가 호출되지 않아야 함


# === P1-2: get_embeddings 배치 요청 테스트 ===

@pytest.mark.asyncio
async def test_get_embeddings_전체_캐시_히트시_api를_호출하지_않는다(monkeypatch, tmp_path):
    """모든 텍스트가 캐시에 있으면 API를 호출하지 않음"""
    cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text1", _DUMMY_EMBEDDING)
    cache.put("text2", _DUMMY_EMBEDDING_2)

    monkeypatch.setattr(embedding.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(embedding_cache, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        raise RuntimeError("API should not be called")

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", lambda **kw: mock_ctx)

    results = await embedding.get_embeddings(["text1", "text2"])

    assert len(results) == 2
    assert results[0] == _DUMMY_EMBEDDING
    assert results[1] == _DUMMY_EMBEDDING_2
    assert not api_called


@pytest.mark.asyncio
async def test_get_embeddings_부분_캐시_히트시_미스_건만_api를_호출한다(monkeypatch, tmp_path):
    """일부만 캐시에 있으면 미스 건만 API 호출"""
    cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "cache.db")
    cache.put("text1", _DUMMY_EMBEDDING)
    # text2는 캐시에 없음

    monkeypatch.setattr(embedding.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(embedding_cache, "get_cache", lambda: cache)

    api_called = False

    async def mock_post(url, json, **kwargs):
        nonlocal api_called
        api_called = True
        input_val = json.get("input", "")
        # 배치 요청인 경우 입력 개수만큼 임베딩 반환
        if isinstance(input_val, list):
            # [vector1, vector2, ...] 형식
            embeddings = [_DUMMY_EMBEDDING_2 for _ in input_val]
            return _MockBatchResponse(embeddings)
        class MockResponse:
            def json(self):
                return {"embeddings": [[_DUMMY_EMBEDDING_2]]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", lambda **kw: mock_ctx)

    results = await embedding.get_embeddings(["text1", "text2"])

    assert len(results) == 2
    assert results[0] == _DUMMY_EMBEDDING  # 캐시 히트
    assert results[1] == _DUMMY_EMBEDDING_2  # API 호출
    assert api_called


@pytest.mark.asyncio
async def test_get_embeddings_결과_순서를_보존한다(monkeypatch, tmp_path):
    """배치 요청 결과의 순서가 입력 순서와 일치"""
    cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "cache.db")
    # text2만 캐시에 있음
    cache.put("text2", _DUMMY_EMBEDDING_2)

    monkeypatch.setattr(embedding.settings, "embedding_cache_enabled", True)
    monkeypatch.setattr(embedding_cache, "get_cache", lambda: cache)

    async def mock_post(url, json, **kwargs):
        input_val = json.get("input", "")
        # 배치 요청인 경우 입력 개수만큼 임베딩 반환
        if isinstance(input_val, list):
            # [vector1, vector2, ...] 형식
            embeddings = [_DUMMY_EMBEDDING for _ in input_val]
            return _MockBatchResponse(embeddings)
        class MockResponse:
            def json(self):
                return {"embeddings": [[_DUMMY_EMBEDDING]]}
            def raise_for_status(self):
                pass
        return MockResponse()

    mock_ctx = _MockAsyncContextManager(post_func=mock_post)
    monkeypatch.setattr("app.services.embedding.httpx.AsyncClient", lambda **kw: mock_ctx)

    results = await embedding.get_embeddings(["text1", "text2", "text3"])

    assert len(results) == 3
    # 순서 보존: text1(API), text2(캐시), text3(API)
    assert results[0] == _DUMMY_EMBEDDING  # API 호출
    assert results[1] == _DUMMY_EMBEDDING_2  # 캐시 히트


# === P1-3: EmbeddingCache 클래스 테스트 ===

class TestEmbeddingCache:
    """임베딩 캐시 클래스 테스트"""

    def test_get_put_기본_동작(self, tmp_path):
        """get/put 기본 동작"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")

        # 처음에는 없음
        assert cache.get("test") is None

        # 저장
        cache.put("test", _DUMMY_EMBEDDING)
        assert cache.get("test") == _DUMMY_EMBEDDING

    def test_get_batch_배치_조회(self, tmp_path):
        """배치 조회 - {인덱스: 임베딩} 반환"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")
        cache.put("text1", _DUMMY_EMBEDDING)
        cache.put("text3", _DUMMY_EMBEDDING_2)

        hits = cache.get_batch(["text1", "text2", "text3"])

        assert hits == {0: _DUMMY_EMBEDDING, 2: _DUMMY_EMBEDDING_2}
        assert 1 not in hits  # text2는 캐시에 없음

    def test_put_batch_배치_저장(self, tmp_path):
        """배치 저장"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")

        cache.put_batch(["text1", "text2"], [_DUMMY_EMBEDDING, _DUMMY_EMBEDDING_2])

        assert cache.get("text1") == _DUMMY_EMBEDDING
        assert cache.get("text2") == _DUMMY_EMBEDDING_2

    def test_stats_히트_률_계산(self, tmp_path):
        """캐시 통계"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")

        # 2회 조회 (miss), 1회 저장, 1회 조회 (hit)
        cache.get("test1")  # miss
        cache.get("test2")  # miss
        cache.put("test1", _DUMMY_EMBEDDING)
        cache.get("test1")  # hit

        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert stats["hit_rate"] == "33.3%"

    def test_clear_캐시_초기화(self, tmp_path):
        """캐시 초기화"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")
        cache.put("test", _DUMMY_EMBEDDING)

        cache.clear()

        assert cache.get("test") is None
        assert cache.count() == 0

    def test_count_항목_수_반환(self, tmp_path):
        """저장된 항목 수 반환"""
        cache = embedding_cache.EmbeddingCache(db_path=tmp_path / "test.db")

        assert cache.count() == 0

        cache.put("test1", _DUMMY_EMBEDDING)
        assert cache.count() == 1

        cache.put("test2", _DUMMY_EMBEDDING_2)
        assert cache.count() == 2
