"""벡터 DB + JSON 기반 저장소 관리

- vector_store: 벡터 저장소 (설정에 따라 ChromaDB 등 선택 가능)
- chunks_collection: vector_store의 별칭 (하위 호환성)
- documents_store: JSON 파일 기반 문서 메타데이터 저장소
"""
from __future__ import annotations

import json
import os

from app.config import settings as app_settings
from app.services.vector_stores.factory import VectorStoreFactory

# 벡터 저장소 인스턴스 (팩토리로 생성)
vector_store = VectorStoreFactory.create()

# 하위 호환성을 위한 별칭
chunks_collection = vector_store


# === JSON 기반 문서 메타데이터 저장소 ===

_DOCS_FILE = os.path.join(app_settings.chroma_persist_dir, "documents.json")


def _ensure_dir():
    os.makedirs(app_settings.chroma_persist_dir, exist_ok=True)


def _load_docs() -> dict[str, dict]:
    if not os.path.exists(_DOCS_FILE):
        return {}
    with open(_DOCS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_docs(docs: dict[str, dict]):
    _ensure_dir()
    with open(_DOCS_FILE, "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)


def add_document(doc_id: str, metadata: dict):
    """문서 메타데이터 저장"""
    docs = _load_docs()
    docs[doc_id] = metadata
    _save_docs(docs)


def get_document(doc_id: str) -> dict | None:
    """문서 메타데이터 조회"""
    docs = _load_docs()
    return docs.get(doc_id)


def list_documents() -> list[dict]:
    """전체 문서 메타데이터 목록"""
    docs = _load_docs()
    return [{"id": k, **v} for k, v in docs.items()]


def delete_document(doc_id: str) -> bool:
    """문서 메타데이터 삭제"""
    docs = _load_docs()
    if doc_id not in docs:
        return False
    del docs[doc_id]
    _save_docs(docs)
    return True
