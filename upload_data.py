"""데이터 파일을 임베딩하여 ChromaDB에 업로드

지원 형식:
  - .txt: 채팅 로그
  - .xlsx: 이슈 데이터 (엑셀)

사용법:
  python upload_data.py                                  # 기본: 엑셀 이슈 데이터
  python upload_data.py data/model_issue_dataset_10000.xlsx
  python upload_data.py data/chat_logs.txt               # 채팅 로그
"""
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone

from app.database import add_document, chunks_collection
from app.services.embedding import get_embeddings
from app.services.parsers import ParserFactory


async def upload_file(filepath: str):
    """범용 파일 업로드 — 파서 팩토리 기반"""
    start = time.time()
    filename = os.path.basename(filepath)

    print(f"파일: {filepath}")
    print(f"파서: {ParserFactory.create(filename).__class__.__name__}")

    # 파서 선택 + 파싱
    parser = ParserFactory.create(filename)

    if filename.endswith((".xlsx", ".xls")):
        parsed_chunks = parser.parse(filepath)
    else:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        parsed_chunks = parser.parse(content)

    print(f"파싱된 청크: {len(parsed_chunks)}건")

    if not parsed_chunks:
        print("파싱 가능한 데이터가 없습니다")
        return

    doc_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    add_document(doc_id, {
        "filename": filename,
        "total_chunks": len(parsed_chunks),
        "created_at": created_at,
    })

    # 배치 임베딩 + 저장
    batch_size = 50
    total_stored = 0

    for i in range(0, len(parsed_chunks), batch_size):
        batch = parsed_chunks[i : i + batch_size]

        texts = [item["embedding_text"] for item in batch]
        embeddings = await get_embeddings(texts)

        chunk_ids = [f"{doc_id}_chunk_{i + j}" for j in range(len(batch))]
        documents = [item["embedding_text"] for item in batch]
        metadatas = [
            {
                "document_id": doc_id,
                "chunk_index": i + j,
                "filename": filename,
                **item["metadata"],
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

        total_stored += len(batch)
        elapsed = time.time() - start
        pct = total_stored / len(parsed_chunks) * 100
        print(f"  [{total_stored}/{len(parsed_chunks)}] {pct:.0f}% ({elapsed:.0f}초)")

    elapsed = time.time() - start
    print(f"\n완료! {total_stored}건 저장, 소요: {elapsed:.0f}초")


if __name__ == "__main__":
    filepath = sys.argv[1] if len(sys.argv) > 1 else "data/model_issue_dataset_10000.xlsx"
    asyncio.run(upload_file(filepath))
