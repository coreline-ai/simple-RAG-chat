"""ChromaDB 벡터 저장소 구현체

ChromaDB를 BaseVectorStore 인터페이스로 감싼다.
"""
from __future__ import annotations

from typing import Any

import chromadb

from app.services.vector_stores.base import BaseVectorStore


class ChromaVectorStore(BaseVectorStore):
    """ChromaDB 벡터 저장소

    ChromaDB 클라이언트를 BaseVectorStore 인터페이스로 감싼다.
    """

    def __init__(self, persist_dir: str, collection_name: str = "chunks"):
        """ChromaDB 벡터 저장소 초기화

        Args:
            persist_dir: DB 저장 경로
            collection_name: 컬렉션 이름
        """
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,  # 임베딩은 외부에서 직접 전달
        )

    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """데이터 추가"""
        self._collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """벡터 유사도 검색"""
        return self._collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results,
            where=where,
            include=include,
        )

    def get(
        self,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
        limit: int | None = None,
    ) -> dict:
        """메타데이터 필터로 조회"""
        # ChromaDB는 include=None을 허용하지 않음
        if include is None:
            include = []
        return self._collection.get(
            where=where,
            include=include,
            limit=limit,
        )

    def delete(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        """데이터 삭제"""
        self._collection.delete(ids=ids, where=where)

    def count(self) -> int:
        """전체 문서 수 반환"""
        return self._collection.count()

    @property
    def collection(self):
        """내부 ChromaDB 컬렉션에 직접 접근 (하위 호환성용)"""
        return self._collection
