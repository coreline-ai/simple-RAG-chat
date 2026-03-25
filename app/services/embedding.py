"""임베딩(Embedding) 서비스

Ollama의 bge-m3 모델을 사용하여 텍스트를 벡터로 변환한다.
캐시가 활성화된 경우 동일 텍스트의 중복 요청을 방지한다.
"""
from __future__ import annotations

import httpx

from app.config import settings


async def get_embedding(text: str) -> list[float]:
    """단일 텍스트의 임베딩 벡터 생성 (캐시 지원)"""
    if settings.embedding_cache_enabled:
        from app.services.embedding_cache import get_cache

        cache = get_cache()
        cached = cache.get(text)
        if cached is not None:
            return cached

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": text},
            timeout=60.0,
        )
        response.raise_for_status()
        embedding = response.json()["embeddings"][0]

    if settings.embedding_cache_enabled:
        cache.put(text, embedding)

    return embedding


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """여러 텍스트의 임베딩 벡터를 일괄 생성 (캐시 지원)"""
    if not texts:
        return []

    if settings.embedding_cache_enabled:
        from app.services.embedding_cache import get_cache

        cache = get_cache()
        hits = cache.get_batch(texts)

        # 캐시 미스인 텍스트만 Ollama에 요청
        miss_indices = [i for i in range(len(texts)) if i not in hits]

        if not miss_indices:
            # 전부 캐시 히트
            return [hits[i] for i in range(len(texts))]

        miss_texts = [texts[i] for i in miss_indices]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/embed",
                json={"model": settings.embedding_model, "input": miss_texts},
                timeout=120.0,
            )
            response.raise_for_status()
            miss_embeddings = response.json()["embeddings"]

        # 캐시에 저장
        cache.put_batch(miss_texts, miss_embeddings)

        # 순서대로 재조합
        result: list[list[float]] = []
        miss_ptr = 0
        for i in range(len(texts)):
            if i in hits:
                result.append(hits[i])
            else:
                result.append(miss_embeddings[miss_ptr])
                miss_ptr += 1
        return result

    # 캐시 비활성화 시 전부 Ollama 요청
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": texts},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["embeddings"]
