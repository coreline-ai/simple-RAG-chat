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

import logging
import time
from collections import Counter

from app.config import settings
from app.database import chunks_collection
from app.services.embedding import get_embedding
from app.services.query_analyzer import QueryAnalysis, analyze_query

logger = logging.getLogger(__name__)

# 쿼리 결과 인메모리 캐시 {(query, top_k): (timestamp, results, analysis)}
_query_cache: dict[tuple[str, int], tuple[float, list[dict], QueryAnalysis]] = {}
_QUERY_CACHE_MAX_SIZE = 256


def invalidate_query_cache() -> None:
    """쿼리 결과 캐시 전체 무효화 (문서 변경 시 호출)"""
    _query_cache.clear()


def _evict_expired_cache(ttl: float) -> None:
    """만료된 캐시 항목 제거 + 크기 제한 초과 시 가장 오래된 항목 제거"""
    now = time.monotonic()
    expired = [k for k, (ts, _, _) in _query_cache.items() if (now - ts) >= ttl]
    for k in expired:
        del _query_cache[k]

    # 크기 제한 초과 시 가장 오래된 항목부터 제거
    if len(_query_cache) > _QUERY_CACHE_MAX_SIZE:
        sorted_keys = sorted(_query_cache, key=lambda k: _query_cache[k][0])
        for k in sorted_keys[: len(_query_cache) - _QUERY_CACHE_MAX_SIZE]:
            del _query_cache[k]


async def search_similar_chunks(
    query: str,
    top_k: int | None = None,
) -> tuple[list[dict], QueryAnalysis]:
    """스마트 검색: LLM 쿼리 분석 → 전략 자동 선택 → 결과 반환

    Returns:
        (검색 결과 리스트, 쿼리 분석 결과) 튜플
    """
    top_k = top_k or settings.top_k

    # TTL 캐시 확인
    ttl = settings.query_cache_ttl_seconds
    if ttl > 0:
        cache_key = (query, top_k)
        cached = _query_cache.get(cache_key)
        if cached and (time.monotonic() - cached[0]) < ttl:
            logger.debug("[캐시 히트] query=%s", query[:50])
            return cached[1], cached[2]

    if chunks_collection.count() == 0:
        empty_analysis = QueryAnalysis({"intent": "search", "strategy": "vector"})
        return [], empty_analysis

    # 1단계: 규칙 기반 쿼리 분석
    analysis = await analyze_query(query)
    logger.debug("[검색전략] strategy=%s, intent=%s", analysis.strategy, analysis.intent)

    # 2단계: 전략에 따른 검색 실행
    if analysis.strategy == "aggregate":
        results = await _search_aggregate(analysis, top_k)
    elif analysis.strategy == "metadata":
        results = await _search_metadata(analysis, top_k)
    elif analysis.strategy == "hybrid":
        results = await _search_hybrid(analysis, query, top_k)
    else:  # vector
        results = await _search_vector(query, top_k)

    # 결과 캐싱 (쓰기 시 만료/크기 정리)
    if ttl > 0:
        _evict_expired_cache(ttl)
        _query_cache[(query, top_k)] = (time.monotonic(), results, analysis)
        _evict_expired_cache(ttl)

    return results, analysis


async def _search_vector(query: str, top_k: int) -> list[dict]:
    """순수 벡터 유사도 검색 (내용 기반)"""
    query_embedding = await get_embedding(query)

    search_k = min(top_k * settings.search_vector_multiplier, chunks_collection.count())
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
        limit=top_k * settings.search_metadata_multiplier,
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
            "assignee": meta.get("assignee", ""),
            "status": meta.get("status", ""),
            "doc_type": meta.get("doc_type", ""),
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
            logger.debug("[하이브리드] 필터 결과 0건, 벡터 검색으로 폴백")
            where = None
    else:
        filtered_count = chunks_collection.count()

    # 검색 텍스트 결정 (분석된 핵심 키워드 우선)
    search_text = analysis.search_text or query
    query_embedding = await get_embedding(search_text)

    search_k = min(top_k * settings.search_hybrid_multiplier, filtered_count if where else chunks_collection.count())
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
            "assignee": meta.get("assignee", ""),
            "status": meta.get("status", ""),
            "doc_type": meta.get("doc_type", ""),
            "date": meta.get("date", ""),
            "time": meta.get("time", ""),
        })

    # 시간순 정렬 후 샘플링 (전체를 LLM에 넘기면 너무 큼)
    items.sort(key=lambda x: (x["date"], x["time"]))
    total_count = len(items)

    # 집계용: 대표 샘플 + 통계 정보 추가
    stats_item = _build_aggregate_stats_item(items, analysis)

    # 균일 샘플링 (시간순 분포 유지)
    sample_size = min(top_k - 1, total_count)
    if sample_size > 0 and total_count > sample_size:
        if _wants_assignee_roster(analysis):
            sampled = _sample_unique_by_key(items, "assignee", sample_size)
        else:
            step = total_count // sample_size
            sampled = [items[i * step] for i in range(sample_size)]
    else:
        sampled = items[:sample_size]

    return [stats_item] + sampled


def _build_aggregate_stats_item(items: list[dict], analysis: QueryAnalysis) -> dict:
    """집계 결과를 LLM 친화적인 요약 청크로 변환"""
    total_count = len(items)
    room_counts = Counter(item["room"] for item in items if item.get("room"))
    user_counts = Counter(item["user"] for item in items if item.get("user"))
    assignee_counts = Counter(item["assignee"] for item in items if item.get("assignee"))
    status_counts = Counter(item["status"] for item in items if item.get("status"))

    stats_lines = [f"[통계 요약] 총 {total_count}건"]

    if assignee_counts and _should_prefer_assignee_summary(analysis, user_counts):
        all_assignees = ", ".join(sorted(assignee_counts))
        assignee_rank = ", ".join(
            f"{name}({count}건)"
            for name, count in sorted(assignee_counts.items(), key=lambda item: (-item[1], item[0]))
        )
        stats_lines.append(f"담당자 전체({len(assignee_counts)}명): {all_assignees}")
        stats_lines.append(f"담당자별 건수: {assignee_rank}")
        if status_counts:
            status_rank = ", ".join(
                f"{status}({count}건)"
                for status, count in sorted(status_counts.items(), key=lambda item: (-item[1], item[0]))
            )
            stats_lines.append(f"상태별: {status_rank}")
    else:
        if room_counts:
            top_rooms = sorted(room_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            stats_lines.append(f"채팅방별: {', '.join(f'{room}({count}건)' for room, count in top_rooms)}")
        if user_counts:
            top_users = sorted(user_counts.items(), key=lambda item: (-item[1], item[0]))[:10]
            stats_lines.append(f"사용자별: {', '.join(f'{user}({count}건)' for user, count in top_users)}")

    return {
        "id": "stats_summary",
        "document_id": "",
        "content": "\n".join(stats_lines),
        "chunk_index": 0,
        "score": 1.0,
        "room": "통계",
        "user": "시스템",
        "date": "",
        "time": "",
    }


def _should_prefer_assignee_summary(analysis: QueryAnalysis, user_counts: Counter[str]) -> bool:
    """이슈 데이터처럼 담당자 기준 요약이 더 적합한지 판단"""
    if not analysis.original_query:
        return not user_counts

    text = f"{analysis.original_query} {analysis.search_text}".strip()
    assignee_keywords = ("담당자", "팀", "팀원", "구성원", "멤버", "참여자")
    return any(keyword in text for keyword in assignee_keywords) or not user_counts


def _wants_assignee_roster(analysis: QueryAnalysis) -> bool:
    """전수 담당자/팀원 목록 질문인지 판단"""
    text = f"{analysis.original_query} {analysis.search_text}".strip()
    target_keywords = ("담당자", "팀", "팀원", "구성원", "멤버", "참여자")
    list_keywords = ("모두", "전체", "전원", "목록", "리스트", "누구", "이름")
    return (
        analysis.intent == "list"
        and any(keyword in text for keyword in target_keywords)
        and any(keyword in text for keyword in list_keywords)
    )


def _sample_unique_by_key(items: list[dict], key: str, limit: int) -> list[dict]:
    """동일 담당자 샘플이 반복되지 않도록 대표 항목만 추출"""
    sampled = []
    seen = set()
    for item in items:
        value = item.get(key)
        if not value or value in seen:
            continue
        seen.add(value)
        sampled.append(item)
        if len(sampled) >= limit:
            break
    return sampled


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
            "assignee": meta.get("assignee", ""),
            "status": meta.get("status", ""),
            "doc_type": meta.get("doc_type", ""),
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
