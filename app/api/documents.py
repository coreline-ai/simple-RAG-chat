"""문서 관리 API 라우터

채팅 로그를 라인 단위로 파싱하여 개별 임베딩 + 메타데이터로 저장한다.
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile

from app.database import add_document, chunks_collection, delete_document, get_document, list_documents
from app.schemas import DocumentListResponse, DocumentResponse, DocumentUploadRequest
from app.services.chunking import parse_and_format
from app.services.embedding import get_embeddings
from app.services.query_analyzer import invalidate_query_analyzer_cache

router = APIRouter(prefix="/documents", tags=["문서 관리"])


async def _process_and_store(filename: str, content: str) -> dict:
    """문서 처리: 라인 파싱 → 임베딩 → 메타데이터와 함께 저장"""
    parsed_lines = parse_and_format(content)
    if not parsed_lines:
        raise HTTPException(status_code=400, detail="파싱 가능한 채팅 라인이 없습니다")

    doc_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    # 문서 메타데이터 저장 (JSON)
    add_document(doc_id, {
        "filename": filename,
        "total_chunks": len(parsed_lines),
        "created_at": created_at,
    })

    # 배치 임베딩 + ChromaDB 저장
    batch_size = 50
    for i in range(0, len(parsed_lines), batch_size):
        batch = parsed_lines[i : i + batch_size]

        # 임베딩용 텍스트 추출
        texts = [item["embedding_text"] for item in batch]
        embeddings = await get_embeddings(texts)

        # ChromaDB 저장 (임베딩 + 원본 + 메타데이터)
        chunk_ids = [f"{doc_id}_line_{i + j}" for j in range(len(batch))]
        documents = [item["embedding_text"] for item in batch]
        metadatas = [
            {
                "document_id": doc_id,
                "chunk_index": i + j,
                "filename": filename,
                "room": item["metadata"]["room"],
                "user": item["metadata"]["user"],
                "date": item["metadata"]["date"],
                "date_int": item["metadata"]["date_int"],
                "time": item["metadata"]["time"],
                "original": item["original"],
            }
            for j, item in enumerate(batch)
        ]

        chunks_collection.add(
            ids=chunk_ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    invalidate_query_analyzer_cache()

    return {
        "id": doc_id,
        "filename": filename,
        "total_chunks": len(parsed_lines),
        "created_at": created_at,
    }


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(request: DocumentUploadRequest):
    """텍스트 문서 업로드 → 라인 파싱 → 임베딩 → DB 저장"""
    doc = await _process_and_store(request.filename, request.content)
    return DocumentResponse(**doc)


@router.post("/upload-file", response_model=DocumentResponse, status_code=201)
async def upload_file(file: UploadFile):
    """파일 업로드 → 라인 파싱 → 임베딩 → DB 저장"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일명이 없습니다")

    content = await file.read()
    text = content.decode("utf-8")

    if not text.strip():
        raise HTTPException(status_code=400, detail="파일 내용이 비어있습니다")

    doc = await _process_and_store(file.filename, text)
    return DocumentResponse(**doc)


@router.get("", response_model=DocumentListResponse)
async def get_documents():
    """저장된 문서 목록 조회"""
    docs = list_documents()
    documents = [DocumentResponse(**d) for d in docs]
    return DocumentListResponse(documents=documents, total=len(documents))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document_detail(document_id: str):
    """특정 문서 상세 조회"""
    doc = get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    return DocumentResponse(id=document_id, **doc)


@router.delete("/{document_id}", status_code=204)
async def remove_document(document_id: str):
    """문서 및 관련 데이터 삭제"""
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    try:
        chunks_collection.delete(where={"document_id": document_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"문서 청크 삭제 실패: {e}") from e

    if not delete_document(document_id):
        raise HTTPException(status_code=500, detail="문서 메타데이터 삭제에 실패했습니다")

    invalidate_query_analyzer_cache()
