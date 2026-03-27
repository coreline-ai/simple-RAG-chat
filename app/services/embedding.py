"""임베딩(Embedding) 서비스

Ollama의 bge-m3 모델을 사용하여 텍스트를 벡터로 변환한다.
캐시가 활성화된 경우 동일 텍스트의 중복 요청을 방지한다.
일시적 오류(timeout/5xx/429)는 bounded retry로 복구를 시도한다.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Ollama 동시 요청 제한 세마포어
_semaphore: asyncio.Semaphore | None = None

_MAX_RETRIES = 3
_RETRY_BACKOFF = 1.0  # 초 단위, 지수 백오프 기본값


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        concurrency = getattr(settings, "embedding_max_concurrency", 3)
        _semaphore = asyncio.Semaphore(concurrency)
    return _semaphore


def reset_semaphore() -> None:
    """세마포어 재생성 (테스트용)"""
    global _semaphore
    _semaphore = None


class EmbeddingError(Exception):
    """임베딩 서비스 호출 실패"""


def _is_retryable(exc: Exception) -> bool:
    """재시도 가능한 오류인지 판단"""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


async def _call_ollama(texts: str | list[str], timeout: float = 120.0) -> list[list[float]]:
    """Ollama 임베딩 API 호출 (세마포어 + bounded retry + 에러 핸들링)"""
    last_exc: Exception | None = None

    for attempt in range(1, _MAX_RETRIES + 1):
        async with _get_semaphore():
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{settings.ollama_base_url}/api/embed",
                        json={"model": settings.embedding_model, "input": texts},
                        timeout=timeout,
                    )
                    response.raise_for_status()
                    return response.json()["embeddings"]
            except httpx.ConnectError as e:
                logger.error("Ollama 서버 연결 실패 (%s): %s", settings.ollama_base_url, e)
                raise EmbeddingError(
                    f"Ollama 서버({settings.ollama_base_url})에 연결할 수 없습니다. "
                    f"Ollama가 실행 중인지 확인하세요."
                ) from e
            except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
                last_exc = e
                if _is_retryable(e) and attempt < _MAX_RETRIES:
                    wait = _RETRY_BACKOFF * (2 ** (attempt - 1))
                    logger.warning(
                        "Ollama 임베딩 재시도 (%d/%d), %.1f초 후: %s",
                        attempt, _MAX_RETRIES, wait, e,
                    )
                    await asyncio.sleep(wait)
                    continue
                # 재시도 불가 또는 최종 실패
                break

    # 최종 실패 — last_exc에서 EmbeddingError 생성
    if isinstance(last_exc, httpx.HTTPStatusError):
        logger.error("Ollama 임베딩 요청 실패 (status=%s): %s", last_exc.response.status_code, last_exc)
        raise EmbeddingError(
            f"임베딩 모델({settings.embedding_model}) 요청 실패: {last_exc.response.status_code}"
        ) from last_exc
    if isinstance(last_exc, httpx.TimeoutException):
        logger.error("Ollama 임베딩 타임아웃 (%d회 재시도 후): %s", _MAX_RETRIES, last_exc)
        raise EmbeddingError("Ollama 임베딩 요청이 타임아웃되었습니다.") from last_exc

    raise EmbeddingError("Ollama 임베딩 요청이 알 수 없는 이유로 실패했습니다.")


async def get_embedding(text: str) -> list[float]:
    """단일 텍스트의 임베딩 벡터 생성 (캐시 지원)"""
    if settings.embedding_cache_enabled:
        from app.services.embedding_cache import get_cache

        cache = get_cache()
        cached = cache.get(text)
        if cached is not None:
            return cached

    embeddings = await _call_ollama(text, timeout=60.0)
    embedding = embeddings[0]

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
        miss_embeddings = await _call_ollama(miss_texts)

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
    return await _call_ollama(texts)
