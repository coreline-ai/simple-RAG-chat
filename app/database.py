"""ChromaDB + JSON 기반 저장소 관리

- chunks_collection: ChromaDB 벡터 저장소 (Ollama 임베딩 직접 전달)
- documents_store: JSON 파일 기반 문서 메타데이터 저장소
"""
import json
import os

import chromadb

from app.config import settings as app_settings

# ChromaDB 클라이언트 (벡터 검색용)
_client = chromadb.PersistentClient(path=app_settings.chroma_persist_dir)

# 청크 벡터 저장용 컬렉션 (임베딩은 외부에서 직접 전달)
chunks_collection = _client.get_or_create_collection(
    name="chunks",
    metadata={"hnsw:space": "cosine"},
    embedding_function=None,
)


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
