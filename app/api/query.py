"""질의(Query) API 라우터

2단계 LLM 파이프라인:
  1단계: 쿼리 분석 (QueryAnalyzer) → 필터 + 전략 자동 결정
  2단계: 검색 결과 기반 답변 생성 (OllamaLLM)
"""
from fastapi import APIRouter

from app.schemas import ChunkResponse, QueryRequest, QueryResponse
from app.services.llm import llm
from app.services.retrieval import search_similar_chunks

router = APIRouter(prefix="/query", tags=["질의 응답"])


@router.post("", response_model=QueryResponse)
async def query(request: QueryRequest):
    """질의 → LLM 쿼리 분석 → 스마트 검색 → LLM 답변 생성

    1. LLM이 질의 의도를 분석 (날짜/채팅방/사용자 필터 자동 추출)
    2. 분석 결과에 따라 최적 검색 전략 선택 (vector/metadata/hybrid/aggregate)
    3. 검색된 컨텍스트로 LLM 답변 생성
    """
    # 스마트 검색 (1단계: 쿼리 분석 + 2단계: 전략별 검색)
    similar_chunks, analysis = await search_similar_chunks(
        query=request.question,
        top_k=request.top_k,
    )

    # 컨텍스트 조합
    max_chars_per_chunk = 500
    context_parts = []
    for chunk in similar_chunks:
        text = chunk["content"][:max_chars_per_chunk]
        context_parts.append(text)
    context = "\n\n---\n\n".join(context_parts)

    # 분석 메타정보를 컨텍스트에 추가 (LLM이 더 정확하게 답변하도록)
    meta_hint = ""
    if analysis.intent == "list":
        meta_hint = "\n\n[힌트: 사용자가 목록/나열을 원합니다. 중복 없이 정리해주세요.]"
    elif analysis.intent == "aggregate":
        meta_hint = "\n\n[힌트: 사용자가 통계/집계를 원합니다. 숫자와 함께 정리해주세요.]"
    elif analysis.intent == "summary":
        meta_hint = "\n\n[힌트: 사용자가 요약을 원합니다. 핵심만 간결하게 정리해주세요.]"

    context += meta_hint

    # LLM 답변 생성 (2단계)
    answer = await llm.generate(prompt=request.question, context=context)

    # 응답 구성
    sources = [
        ChunkResponse(
            id=chunk["id"],
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            score=chunk["score"],
        )
        for chunk in similar_chunks
    ]

    return QueryResponse(
        question=request.question,
        answer=answer,
        sources=sources,
    )
