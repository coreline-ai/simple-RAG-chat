"""질의(Query) API 라우터

2단계 파이프라인:
  1단계: 규칙 기반 쿼리 분석 (QueryAnalyzer) → 필터 + 전략 자동 결정
  2단계: 검색 결과 기반 LLM 답변 생성
"""
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.schemas import ChunkResponse, QueryRequest, QueryResponse
from app.services.llm import llm
from app.services.retrieval import search_similar_chunks

router = APIRouter(prefix="/query", tags=["질의 응답"])


@router.post("", response_model=QueryResponse)
async def query(request: QueryRequest):
    """질의 → 규칙 기반 쿼리 분석 → 스마트 검색 → LLM 답변 생성

    1. 규칙 기반 분석기가 질의 의도를 분류 (날짜/채팅방/사용자 필터 자동 추출)
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
        meta_hint = (
            "\n\n[힌트: 사용자가 목록/나열을 원합니다. "
            "컨텍스트에 있는 후보를 중복 없이 모두 정리하고, "
            "전수 목록이 아닐 수 있으면 그 점을 명시해주세요.]"
        )
    elif analysis.intent == "aggregate":
        meta_hint = "\n\n[힌트: 사용자가 통계/집계를 원합니다. 숫자와 함께 정리해주세요.]"
    elif analysis.intent == "summary":
        meta_hint = "\n\n[힌트: 사용자가 요약을 원합니다. 핵심만 간결하게 정리해주세요.]"

    context += meta_hint

    # LLM 답변 생성 (2단계)
    try:
        answer = await llm.generate(prompt=request.question, context=context)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

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


@router.post("/stream")
async def query_stream(request: QueryRequest):
    """SSE 스트리밍 질의 응답

    첫 토큰을 0.5~2초 내 전송하여 체감 응답 시간을 개선합니다.
    기존 /query 엔드포인트와 하위 호환됩니다.
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

    # 분석 메타정보를 컨텍스트에 추가
    meta_hint = ""
    if analysis.intent == "list":
        meta_hint = (
            "\n\n[힌트: 사용자가 목록/나열을 원합니다. "
            "컨텍스트에 있는 후보를 중복 없이 모두 정리하고, "
            "전수 목록이 아닐 수 있으면 그 점을 명시해주세요.]"
        )
    elif analysis.intent == "aggregate":
        meta_hint = "\n\n[힌트: 사용자가 통계/집계를 원합니다. 숫자와 함께 정리해주세요.]"
    elif analysis.intent == "summary":
        meta_hint = "\n\n[힌트: 사용자가 요약을 원합니다. 핵심만 간결하게 정리해주세요.]"

    context += meta_hint

    async def event_generator():
        """SSE 이벤트 생성기"""
        try:
            # 토큰 스트리밍
            async for token in llm.generate_stream(request.question, context):
                yield f"data: {json.dumps({'token': token, 'done': False}, ensure_ascii=False)}\n\n"

            # 완료 메시지 + 출처
            sources = [
                {
                    "id": chunk["id"],
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "score": chunk["score"],
                }
                for chunk in similar_chunks
            ]
            yield f"data: {json.dumps({'done': True, 'sources': sources}, ensure_ascii=False)}\n\n"

        except Exception as e:
            # 에러 메시지 전송
            yield f"data: {json.dumps({'error': str(e), 'done': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx 버퍼링 방지
        },
    )
