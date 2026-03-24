"""벡터 저장소 팩토리

설정에 따라 적절한 벡터 DB 구현체를 생성한다.
"""
from __future__ import annotations

from app.config import settings
from app.services.vector_stores.base import BaseVectorStore
from app.services.vector_stores.chroma_store import ChromaVectorStore


class VectorStoreFactory:
    """벡터 저장소 팩토리

    설정(vector_db_type)에 따라 적절한 구현체를 생성한다.
    """

    @staticmethod
    def create() -> BaseVectorStore:
        """벡터 저장소 인스턴스 생성

        Returns:
            BaseVectorStore 구현체 인스턴스

        Raises:
            ValueError: 지원하지 않는 vector_db_type인 경우
        """
        db_type = settings.vector_db_type.lower()

        if db_type == "chroma":
            return ChromaVectorStore(
                persist_dir=settings.chroma_persist_dir,
                collection_name="chunks",
            )
        # 추후 확장:
        # elif db_type == "qdrant":
        #     return QdrantVectorStore(...)
        # elif db_type == "pgvector":
        #     return PgVectorStore(...)
        else:
            raise ValueError(
                f"지원하지 않는 벡터 DB 타입: {settings.vector_db_type}. "
                f"지원 가능한 값: chroma"
            )
