"""벡터 검색(Retrieval) 서비스 - 스마트 라우팅

LLM 쿼리 분석기를 통해 질의 의도를 파악하고,
최적의 검색 전략(vector / metadata / hybrid / aggregate)을 자동 선택한다.

흐름:
  1. QueryAnalyzer가 질의를 분석 → 필터 + 전략 결정
  2. 전략에 따라 검색 실행:
     - vector: 순수 벡터 유사도 검색
     - metadata: 메타데이터 필터링만 (날짜/채팅방/사용자)
     - hybrid: 메타데이터 필터 + 벡터 검색 (기본)
     - aggregate: 메타데이터 그룹핑/집계 (통계)
  3. 결과를 채팅방별 그룹핑하여 반환
"""
from __future__ import annotations

from app.config import settings
from app.database import chunks_collection
from app.services.embedding import get_embedding
from app.services.query_analyzer import QueryAnalysis, analyze_query


async def search_similar_chunks(
    query: str,
    top_k: int | None = None,
) -> tuple[list[dict], QueryAnalysis]:
    """스마트 검색: LLM 쿼리 분석 → 전략 자동 선택 → 결과 반환

    Returns:
        (검색 결과 리스트, 쿼리 분석 결과) 튜플
    """
    top_k = top_k or settings.top_k

    if chunks_collection.count() == 0:
        empty_analysis = QueryAnalysis({"intent": "search", "strategy": "vector"})
        return [], empty_analysis

    # 1단계: LLM 쿼리 분석
    analysis = await analyze_query(query)
    print(f"[검색전략] strategy={analysis.strategy}, intent={analysis.intent}")

    # 2단계: 전략에 따른 검색 실행
    if analysis.strategy == "aggregate":
        results = await _search_aggregate(analysis, top_k)
    elif analysis.strategy == "metadata":
        results = await _search_metadata(analysis, top_k)
    elif analysis.strategy == "hybrid":
        results = await _search_hybrid(analysis, query, top_k)
    else:  # vector
        results = await _search_vector(query, top_k)

    return results, analysis


async def _search_vector(query: str, top_k: int) -> list[dict]:
    """순수 벡터 유사도 검색 (내용 기반)"""
    query_embedding = await get_embedding(query)

    search_k = min(top_k * 3, chunks_collection.count())
    results = chunks_collection.query(
        query_embeddings=[query_embedding],
        n_results=search_k,
        include=["documents", "metadatas", "distances"],
    )

    return _format_results(results, top_k)


async def _search_metadata(analysis: QueryAnalysis, top_k: int) -> list[dict]:
    """메타데이터 필터링만 사용 (날짜/채팅방/사용자 조건)"""
    where = analysis.to_chroma_where()
    if not where:
        # 필터가 없으면 벡터 검색으로 폴백
        return await _search_vector(analysis.search_text or "", top_k)

    # 메타데이터 필터로 직접 조회
    filtered = chunks_collection.get(
        where=where,
        include=["documents", "metadatas"],
        limit=top_k * 5,  # 여유 있게 가져옴
    )

    if not filtered["ids"]:
        return []

    items = []
    for i in range(len(filtered["ids"])):
        meta = filtered["metadatas"][i]
        items.append({
            "id": filtered["ids"][i],
            "document_id": meta.get("document_id", ""),
            "content": meta.get("original", filtered["documents"][i]),
            "chunk_index": meta.get("chunk_index", 0),
            "score": 1.0,  # 메타데이터 정확 매칭
            "room": meta.get("room", "unknown"),
            "user": meta.get("user", ""),
            "date": meta.get("date", ""),
            "time": meta.get("time", ""),
        })

    # 시간순 정렬
    items.sort(key=lambda x: (x["date"], x["time"]))
    return items[:top_k]


async def _search_hybrid(analysis: QueryAnalysis, query: str, top_k: int) -> list[dict]:
    """하이브리드: 메타데이터 필터 + 벡터 검색"""
    where = analysis.to_chroma_where()

    # 필터 결과 확인
    if where:
        filtered = chunks_collection.get(where=where, include=["metadatas"])
        filtered_count = len(filtered["ids"])
        if filtered_count == 0:
            print(f"[하이브리드] 필터 결과 0건, 벡터 검색으로 폴백")
            where = None
    else:
        filtered_count = chunks_collection.count()

    # 검색 텍스트 결정 (분석된 핵심 키워드 우선)
    search_text = analysis.search_text or query
    query_embedding = await get_embedding(search_text)

    search_k = min(top_k * 4, filtered_count if where else chunks_collection.count())
    if search_k == 0:
        search_k = top_k

    results = chunks_collection.query(
        query_embeddings=[query_embedding],
        n_results=search_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    return _format_results(results, top_k)


async def _search_aggregate(analysis: QueryAnalysis, top_k: int) -> list[dict]:
    """집계/통계: 메타데이터 기반 그룹핑"""
    where = analysis.to_chroma_where()

    # 전체 또는 필터된 데이터 가져오기
    get_kwargs = {
        "include": ["documents", "metadatas"],
    }
    if where:
        get_kwargs["where"] = where

    # 집계는 많은 데이터가 필요할 수 있음
    all_data = chunks_collection.get(**get_kwargs)

    if not all_data["ids"]:
        return []

    # 집계 결과를 텍스트로 변환
    items = []
    for i in range(len(all_data["ids"])):
        meta = all_data["metadatas"][i]
        items.append({
            "id": all_data["ids"][i],
            "document_id": meta.get("document_id", ""),
            "content": meta.get("original", all_data["documents"][i]),
            "chunk_index": meta.get("chunk_index", 0),
            "score": 1.0,
            "room": meta.get("room", "unknown"),
            "user": meta.get("user", ""),
            "date": meta.get("date", ""),
            "time": meta.get("time", ""),
        })

    # 시간순 정렬 후 샘플링 (전체를 LLM에 넘기면 너무 큼)
    items.sort(key=lambda x: (x["date"], x["time"]))

    # 집계용: 대표 샘플 + 통계 정보 추가
    total_count = len(items)

    # 채팅방별/사용자별 카운트
    room_counts: dict[str, int] = {}
    user_counts: dict[str, int] = {}
    for item in items:
        room_counts[item["room"]] = room_counts.get(item["room"], 0) + 1
        user_counts[item["user"]] = user_counts.get(item["user"], 0) + 1

    # 통계 요약을 첫 번째 항목으로 추가
    stats_text = f"[통계 요약] 총 {total_count}건"
    if room_counts:
        top_rooms = sorted(room_counts.items(), key=lambda x: -x[1])[:10]
        stats_text += f"\n채팅방별: {', '.join(f'{r}({c}건)' for r, c in top_rooms)}"
    if user_counts:
        top_users = sorted(user_counts.items(), key=lambda x: -x[1])[:10]
        stats_text += f"\n사용자별: {', '.join(f'{u}({c}건)' for u, c in top_users)}"

    stats_item = {
        "id": "stats_summary",
        "document_id": "",
        "content": stats_text,
        "chunk_index": 0,
        "score": 1.0,
        "room": "통계",
        "user": "시스템",
        "date": "",
        "time": "",
    }

    # 균일 샘플링 (시간순 분포 유지)
    sample_size = min(top_k - 1, total_count)
    if sample_size > 0 and total_count > sample_size:
        step = total_count // sample_size
        sampled = [items[i * step] for i in range(sample_size)]
    else:
        sampled = items[:sample_size]

    return [stats_item] + sampled


def _format_results(results: dict, top_k: int) -> list[dict]:
    """ChromaDB 쿼리 결과를 표준 형식으로 변환 + 채팅방별 그룹핑"""
    if not results["ids"][0]:
        return []

    room_groups: dict[str, list[dict]] = {}
    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        distance = results["distances"][0][i]
        room = meta.get("room", "unknown")

        item = {
            "id": results["ids"][0][i],
            "document_id": meta.get("document_id", ""),
            "content": meta.get("original", results["documents"][0][i]),
            "chunk_index": meta.get("chunk_index", 0),
            "score": round(1 - distance, 4),
            "room": room,
            "user": meta.get("user", ""),
            "date": meta.get("date", ""),
            "time": meta.get("time", ""),
        }
        room_groups.setdefault(room, []).append(item)

    # 각 채팅방 내 시간순 정렬
    for room in room_groups:
        room_groups[room].sort(key=lambda x: (x["date"], x["time"]))

    # 가장 많이 매칭된 채팅방 순으로 결과 조합
    sorted_rooms = sorted(room_groups.items(), key=lambda x: -len(x[1]))

    final_results = []
    for room, items in sorted_rooms:
        for item in items:
            if len(final_results) >= top_k:
                break
            final_results.append(item)
        if len(final_results) >= top_k:
            break

    return final_results
