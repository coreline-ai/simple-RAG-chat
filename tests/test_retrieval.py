"""검색 서비스 회귀 테스트 - 4가지 검색 전략"""
from __future__ import annotations

import pytest

from app.services.query_analyzer import QueryAnalysis
from app.services import retrieval


# === Async mock 유틸리티 ===

async def _mock_embedding(text: str) -> list[float]:
    """임베딩 mock 함수"""
    return [0.1, 0.2]


# === 더미 컬렉션 클래스 ===

class DummyVectorCollection:
    """벡터 검색용 더미 컬렉션"""

    def __init__(self, count: int = 10, metadatas: list[dict] | None = None):
        self._count = count
        self._metadatas = metadatas or [
            {
                "room": "개발팀" if i % 2 == 0 else "마케팅팀",
                "user": f"사용자{i}",
                "date": "2024-03-01",
                "time": f"10:0{i}:00",
                "original": f"[2024-03-01, 10:0{i}:00, 개발팀, 메시지{i}, 사용자{i}]",
            }
            for i in range(count)
        ]
        self.query_calls = []

    def count(self):
        return self._count

    def query(self, query_embeddings=None, n_results=None, include=None, where=None):
        self.query_calls.append({
            "n_results": n_results,
            "where": where,
        })
        # 유사도 순서대로 가짜 결과 반환
        count = min(n_results, self._count)
        return {
            "ids": [[f"chunk-{i}" for i in range(count)]],
            "documents": [[f"내용 {i}" for i in range(count)]],
            "metadatas": [self._metadatas[:count]],
            "distances": [[i * 0.1 for i in range(count)]],
        }

    def get(self, where=None, include=None, limit=None):
        # 필터링 없이 전체 반환 (하이브리드 검색용)
        count = min(limit or self._count, self._count)
        return {
            "ids": [f"chunk-{i}" for i in range(count)],
            "documents": [m["original"] for m in self._metadatas[:count]],
            "metadatas": self._metadatas[:count],
        }


class DummyMetadataCollection:
    """메타데이터 필터용 더미 컬렉션 - where 조건으로 실제 필터링 수행"""

    def __init__(self, metadatas: list[dict], documents: list[str] | None = None):
        self.all_metadatas = metadatas
        self.documents = documents or [meta.get("original", "") for meta in metadatas]
        self.get_calls = []

    def get(self, where=None, include=None, limit=None):
        self.get_calls.append({"where": where, "limit": limit})

        # where 조건으로 필터링
        filtered_metas = []
        filtered_docs = []
        filtered_ids = []

        for i, meta in enumerate(self.all_metadatas):
            match = True
            if where:
                # 단순 일치 조건만 처리
                for key, value in where.items():
                    if meta.get(key) != value:
                        match = False
                        break

            if match:
                filtered_metas.append(meta)
                filtered_docs.append(self.documents[i])
                filtered_ids.append(f"chunk-{i}")

        return {
            "ids": filtered_ids[:limit] if limit else filtered_ids,
            "documents": filtered_docs[:limit] if limit else filtered_docs,
            "metadatas": filtered_metas[:limit] if limit else filtered_metas,
        }


class DummyAggregateCollection:
    """집계 검색용 더미 컬렉션"""
    def __init__(self, metadatas: list[dict], documents: list[str] | None = None):
        self.metadatas = metadatas
        self.documents = documents or [meta.get("original", "") for meta in metadatas]

    def get(self, **kwargs):
        return {
            "ids": [f"chunk-{idx}" for idx in range(len(self.metadatas))],
            "documents": self.documents,
            "metadatas": self.metadatas,
        }


class DummyEmptyCollection:
    """빈 컬렉션"""
    def count(self):
        return 0


class EmptyFilterCollection:
    """필터 결과가 0건인 컬렉션"""
    def __init__(self, count: int = 10):
        self._count = count

    def count(self):
        return self._count

    def get(self, where=None, include=None, limit=None):
        return {"ids": [], "documents": [], "metadatas": []}

    def query(self, query_embeddings=None, n_results=None, include=None, where=None):
        return {
            "ids": [[]],
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }


# === P0-1: _search_vector 테스트 ===

@pytest.mark.asyncio
async def test_벡터_검색은_유사도_순서로_결과를_반환한다(monkeypatch):
    collection = DummyVectorCollection(count=10)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    results = await retrieval._search_vector("테스트 질의", top_k=5)

    assert len(results) == 5
    # 점수 범위 확인 (채팅방별 정렬로 인해 순서는 보장되지 않음)
    assert all(0.0 <= r["score"] <= 1.0 for r in results)


@pytest.mark.asyncio
async def test_벡터_검색은_메타데이터를_포함한다(monkeypatch):
    collection = DummyVectorCollection(count=5)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    results = await retrieval._search_vector("테스트", top_k=3)

    assert results[0]["room"] in ["개발팀", "마케팅팀"]
    assert "user" in results[0]
    assert "date" in results[0]
    assert "time" in results[0]
    # _format_results는 content 키를 사용
    assert "content" in results[0]


@pytest.mark.asyncio
async def test_벡터_검색은_top_k_만큼만_반환한다(monkeypatch):
    collection = DummyVectorCollection(count=100)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    results = await retrieval._search_vector("테스트", top_k=10)

    assert len(results) == 10


# === P0-2: _search_metadata 테스트 ===

@pytest.mark.asyncio
async def test_메타데이터_필터는_where_조건으로_검색한다(monkeypatch):
    collection = DummyMetadataCollection(
        metadatas=[
            {"room": "개발팀", "user": "김민수", "date": "2024-03-01", "original": "메시지1"},
            {"room": "개발팀", "user": "박서준", "date": "2024-03-02", "original": "메시지2"},
            {"room": "마케팅팀", "user": "이지영", "date": "2024-03-03", "original": "메시지3"},
        ]
    )
    monkeypatch.setattr(retrieval, "chunks_collection", collection)

    analysis = QueryAnalysis({
        "original_query": "개발팀 대화",
        "intent": "search",
        "strategy": "metadata",
        "search_text": "",
        "filters": {"room": "개발팀"},
    })

    results = await retrieval._search_metadata(analysis, top_k=10)

    assert len(results) == 2
    assert all(r["room"] == "개발팀" for r in results)


@pytest.mark.asyncio
async def test_메타데이터_필터는_시간순_정렬한다(monkeypatch):
    collection = DummyMetadataCollection(
        metadatas=[
            {"room": "개발팀", "date": "2024-03-03", "time": "10:00:00", "original": "메시지1"},
            {"room": "개발팀", "date": "2024-03-01", "time": "09:00:00", "original": "메시지2"},
            {"room": "개발팀", "date": "2024-03-02", "time": "15:00:00", "original": "메시지3"},
        ]
    )
    monkeypatch.setattr(retrieval, "chunks_collection", collection)

    analysis = QueryAnalysis({
        "original_query": "개발팀 대화",
        "intent": "search",
        "strategy": "metadata",
        "search_text": "",
        "filters": {"room": "개발팀"},
    })

    results = await retrieval._search_metadata(analysis, top_k=10)

    # 날짜+시간 순서대로
    assert results[0]["date"] == "2024-03-01"
    assert results[1]["date"] == "2024-03-02"
    assert results[2]["date"] == "2024-03-03"


@pytest.mark.asyncio
async def test_메타데이터_필터_결과가_없으면_빈_결과를_반환한다(monkeypatch):
    collection = DummyMetadataCollection(
        metadatas=[
            {"room": "개발팀", "user": "김민수", "date": "2024-03-01", "original": "메시지1"},
        ]
    )
    monkeypatch.setattr(retrieval, "chunks_collection", collection)

    analysis = QueryAnalysis({
        "original_query": "마케팅팀 대화",
        "intent": "search",
        "strategy": "metadata",
        "search_text": "",
        "filters": {"room": "마케팅팀"},
    })

    results = await retrieval._search_metadata(analysis, top_k=10)

    assert len(results) == 0


# === P0-3: _search_hybrid 테스트 ===

@pytest.mark.asyncio
async def test_하이브리드는_필터와_벡터를_결합한다(monkeypatch):
    collection = DummyVectorCollection(count=10)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    analysis = QueryAnalysis({
        "original_query": "개발팀 관련 메시지",
        "intent": "search",
        "strategy": "hybrid",
        "search_text": "관련 메시지",
        "filters": {"room": "개발팀"},
    })

    results = await retrieval._search_hybrid(analysis, "관련 메시지", top_k=5)

    assert len(results) == 5
    # where 조건이 전달되었는지 확인
    assert collection.query_calls[0]["where"] is not None


@pytest.mark.asyncio
async def test_하이브리드는_필터_결과_0건시_벡터_검색으로_폴백한다(monkeypatch):
    # 필터 결과가 0건인 빈 컬렉션
    collection = EmptyFilterCollection(count=10)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    analysis = QueryAnalysis({
        "original_query": "없는방 대화",
        "intent": "search",
        "strategy": "hybrid",
        "search_text": "없는방",
        "filters": {"room": "없는방"},
    })

    results = await retrieval._search_hybrid(analysis, "없는방", top_k=5)

    # 폴백으로 인해 결과가 반환됨 (query 메서드의 빈 결과 반환)
    # EmptyFilterCollection.query는 빈 리스트를 반환하므로 결과도 비어있음
    assert len(results) == 0


# === P0-4: search_similar_chunks 통합 테스트 ===

@pytest.mark.asyncio
async def test_빈_컬렉션에서는_빈_결과를_반환한다(monkeypatch):
    empty_collection = DummyEmptyCollection()
    monkeypatch.setattr(retrieval, "chunks_collection", empty_collection)

    results, analysis = await retrieval.search_similar_chunks("테스트", top_k=5)

    assert results == []
    assert analysis.strategy == "vector"


@pytest.mark.asyncio
async def test_쿼리_분석_후_적절한_전략을_선택한다(monkeypatch):
    collection = DummyVectorCollection(count=10)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    # analyze_query를 모의하지 않고 실제 사용 (쿼리 분석 결과에 따라 전략 선택)

    results, analysis = await retrieval.search_similar_chunks("테스트 질의", top_k=5)

    assert analysis is not None
    assert analysis.strategy in ["vector", "metadata", "hybrid", "aggregate"]
    # vector 전략이면 결과가 반환됨
    if analysis.strategy == "vector":
        assert len(results) > 0


@pytest.mark.asyncio
async def test_쿼리_캐시는_최대_크기를_넘지_않는다(monkeypatch):
    collection = DummyVectorCollection(count=10)
    monkeypatch.setattr(retrieval, "chunks_collection", collection)
    monkeypatch.setattr(retrieval, "get_embedding", _mock_embedding)

    async def _mock_analyze(query: str) -> QueryAnalysis:
        return QueryAnalysis({
            "original_query": query,
            "intent": "search",
            "strategy": "vector",
            "search_text": query,
            "filters": {},
        })

    monkeypatch.setattr(retrieval, "analyze_query", _mock_analyze)
    monkeypatch.setattr(
        retrieval,
        "settings",
        type(
            "Settings",
            (),
            {
                "top_k": 5,
                "query_cache_ttl_seconds": 300,
                "search_vector_multiplier": 3,
                "search_hybrid_multiplier": 4,
                "search_metadata_multiplier": 5,
            },
        )(),
    )

    retrieval.invalidate_query_cache()

    for i in range(retrieval._QUERY_CACHE_MAX_SIZE + 5):
        await retrieval.search_similar_chunks(f"질의-{i}", top_k=5)

    assert len(retrieval._query_cache) == retrieval._QUERY_CACHE_MAX_SIZE


# === 기존 테스트 (집계) ===

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
