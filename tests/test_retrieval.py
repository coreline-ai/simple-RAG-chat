"""검색 집계 회귀 테스트"""
from __future__ import annotations

import pytest

from app.services.query_analyzer import QueryAnalysis
from app.services import retrieval


class DummyAggregateCollection:
    def __init__(self, metadatas: list[dict], documents: list[str] | None = None):
        self.metadatas = metadatas
        self.documents = documents or [meta.get("original", "") for meta in metadatas]

    def get(self, **kwargs):
        return {
            "ids": [f"chunk-{idx}" for idx in range(len(self.metadatas))],
            "documents": self.documents,
            "metadatas": self.metadatas,
        }


@pytest.mark.asyncio
async def test_이슈_담당자_목록은_전수_요약을_앞에_붙인다(monkeypatch):
    collection = DummyAggregateCollection(
        metadatas=[
            {
                "original": "[담당자] Hyunwoo",
                "date": "2025-02-09",
                "assignee": "Hyunwoo",
                "status": "진행",
                "doc_type": "issue",
            },
            {
                "original": "[담당자] Seoyeon",
                "date": "2025-02-14",
                "assignee": "Seoyeon",
                "status": "완료",
                "doc_type": "issue",
            },
            {
                "original": "[담당자] Seoyeon",
                "date": "2025-03-20",
                "assignee": "Seoyeon",
                "status": "진행",
                "doc_type": "issue",
            },
            {
                "original": "[담당자] Taehun",
                "date": "2025-07-21",
                "assignee": "Taehun",
                "status": "완료",
                "doc_type": "issue",
            },
        ]
    )
    monkeypatch.setattr(retrieval, "chunks_collection", collection)

    analysis = QueryAnalysis(
        {
            "original_query": "현재 팀 모두 알려줘",
            "intent": "list",
            "strategy": "aggregate",
            "search_text": "현재 팀 모두 알려주",
        }
    )

    results = await retrieval._search_aggregate(analysis, top_k=5)

    assert results[0]["id"] == "stats_summary"
    assert "담당자 전체(3명): Hyunwoo, Seoyeon, Taehun" in results[0]["content"]
    assert "담당자별 건수: Seoyeon(2건), Hyunwoo(1건), Taehun(1건)" in results[0]["content"]
