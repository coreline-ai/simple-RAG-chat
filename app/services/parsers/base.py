"""파서 추상 기반 클래스

모든 데이터 파서가 구현해야 하는 인터페이스를 정의한다.
반환 형식: [{"embedding_text": str, "original": str, "metadata": dict}, ...]
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseParser(ABC):
    """데이터 파서 인터페이스"""

    @abstractmethod
    def parse(self, source: Any) -> list[dict]:
        """데이터를 파싱하여 임베딩 가능한 청크 리스트 반환

        Returns:
            list[dict]: 각 항목은 다음 키를 포함:
                - embedding_text (str): 벡터 임베딩할 텍스트
                - original (str): 원본 데이터 텍스트
                - metadata (dict): ChromaDB 메타데이터 필터용
        """

    @abstractmethod
    def detect(self, filename: str) -> bool:
        """이 파서가 해당 파일을 처리할 수 있는지 판별"""
