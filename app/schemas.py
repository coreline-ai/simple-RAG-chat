"""Pydantic 요청/응답 스키마"""
from typing import Optional

from pydantic import BaseModel


# === 문서 관련 스키마 ===

class DocumentUploadRequest(BaseModel):
    """문서 업로드 요청 (텍스트 직접 입력)"""
    filename: str
    content: str


class ChunkResponse(BaseModel):
    """청크 응답"""
    id: str
    chunk_index: int
    content: str
    score: Optional[float] = None


class DocumentResponse(BaseModel):
    """문서 응답"""
    id: str
    filename: str
    total_chunks: int
    created_at: str


class DocumentListResponse(BaseModel):
    """문서 목록 응답"""
    documents: list[DocumentResponse]
    total: int


# === 질의 관련 스키마 ===

class QueryRequest(BaseModel):
    """질의 요청"""
    question: str
    top_k: Optional[int] = None


class QueryResponse(BaseModel):
    """질의 응답"""
    question: str
    answer: str
    sources: list[ChunkResponse]
