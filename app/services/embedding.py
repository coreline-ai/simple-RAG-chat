"""임베딩(Embedding) 서비스

Ollama의 nomic-embed-text 모델을 사용하여 텍스트를 벡터로 변환한다.
"""
import httpx

from app.config import settings


async def get_embedding(text: str) -> list[float]:
    """단일 텍스트의 임베딩 벡터 생성

    Args:
        text: 임베딩할 텍스트

    Returns:
        임베딩 벡터 (float 리스트)
    """
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": text},
            timeout=60.0,
        )
        response.raise_for_status()
        return response.json()["embeddings"][0]


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """여러 텍스트의 임베딩 벡터를 일괄 생성

    Args:
        texts: 임베딩할 텍스트 리스트

    Returns:
        임베딩 벡터 리스트
    """
    if not texts:
        return []

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embedding_model, "input": texts},
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["embeddings"]
