"""벡터 저장소 추상화 기본 클래스

벡터 DB 공통 인터페이스를 정의한다.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VectorStoreFilter:
    """벡터 DB 공통 필터 형식

    채팅 로그 + 이슈 데이터 검색용 메타데이터 필터를 표현한다.
    """

    def __init__(
        self,
        room: str | None = None,
        user: str | None = None,
        date: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        document_id: str | None = None,
        assignee: str | None = None,
        status: str | None = None,
        doc_type: str | None = None,
    ):
        self.room = room
        self.user = user
        self.date = date
        self.date_from = date_from
        self.date_to = date_to
        self.assignee = assignee
        self.status = status
        self.doc_type = doc_type
        self.document_id = document_id

    def __repr__(self) -> str:
        return (
            f"VectorStoreFilter(room={self.room}, user={self.user}, "
            f"date={self.date}, date_from={self.date_from}, date_to={self.date_to}, "
            f"document_id={self.document_id})"
        )


class BaseVectorStore(ABC):
    """벡터 저장소 추상화 인터페이스

    모든 벡터 DB 구현체가 따라야 할 공통 인터페이스를 정의한다.
    """

    @abstractmethod
    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """데이터 추가

        Args:
            ids: 문서 ID 리스트
            documents: 문서 텍스트 리스트
            embeddings: 임베딩 벡터 리스트 (None이면 내부에서 생성)
            metadatas: 메타데이터 딕셔너리 리스트
        """

    @abstractmethod
    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict:
        """벡터 유사도 검색

        Args:
            query_embeddings: 쿼리 임베딩 벡터 리스트
            n_results: 반환할 결과 수
            where: 메타데이터 필터 조건
            include: 포함할 필드 리스트 (documents, metadatas, distances 등)

        Returns:
            검색 결과 딕셔너리 (ids, documents, metadatas, distances 등)
        """

    @abstractmethod
    def get(
        self,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
        limit: int | None = None,
    ) -> dict:
        """메타데이터 필터로 조회

        Args:
            where: 메타데이터 필터 조건
            include: 포함할 필드 리스트
            limit: 최대 반환 수

        Returns:
            조회 결과 딕셔너리 (ids, documents, metadatas 등)
        """

    @abstractmethod
    def delete(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
    ) -> None:
        """데이터 삭제

        Args:
            ids: 삭제할 ID 리스트
            where: 메타데이터 필터 조건
        """

    @abstractmethod
    def count(self) -> int:
        """전체 문서 수 반환

        Returns:
            저장된 문서 수
        """
