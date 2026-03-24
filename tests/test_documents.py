"""문서 API 단위 테스트"""
import pytest
from fastapi import HTTPException

from app.api import documents as documents_api


class DummyChunksCollection:
    """문서 삭제용 더미 컬렉션"""

    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.calls = []

    def delete(self, ids=None, where=None):
        self.calls.append({"ids": ids, "where": where})
        if self.should_fail:
            raise RuntimeError("delete failed")


@pytest.mark.asyncio
async def test_remove_document는_청크와_메타데이터를_삭제한다(monkeypatch):
    collection = DummyChunksCollection()
    deleted = []
    invalidated = []

    monkeypatch.setattr(documents_api, "chunks_collection", collection)
    monkeypatch.setattr(documents_api, "get_document", lambda document_id: {"filename": "chat.txt"})
    monkeypatch.setattr(
        documents_api,
        "delete_document",
        lambda document_id: deleted.append(document_id) or True,
    )
    monkeypatch.setattr(
        documents_api,
        "invalidate_query_analyzer_cache",
        lambda: invalidated.append(True),
    )

    result = await documents_api.remove_document("doc-1")

    assert result is None
    assert collection.calls == [{"ids": None, "where": {"document_id": "doc-1"}}]
    assert deleted == ["doc-1"]
    assert invalidated == [True]


@pytest.mark.asyncio
async def test_remove_document는_청크삭제_실패시_메타데이터를_보존한다(monkeypatch):
    collection = DummyChunksCollection(should_fail=True)
    deleted = []

    monkeypatch.setattr(documents_api, "chunks_collection", collection)
    monkeypatch.setattr(documents_api, "get_document", lambda document_id: {"filename": "chat.txt"})
    monkeypatch.setattr(
        documents_api,
        "delete_document",
        lambda document_id: deleted.append(document_id) or True,
    )

    with pytest.raises(HTTPException, match="문서 청크 삭제 실패") as exc_info:
        await documents_api.remove_document("doc-1")

    assert exc_info.value.status_code == 500
    assert deleted == []
