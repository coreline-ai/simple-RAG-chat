"""1만건 채팅 로그를 라인 단위로 임베딩하여 업로드"""
import asyncio
import time
import uuid
from datetime import datetime, timezone

from app.database import add_document, chunks_collection
from app.services.chunking import parse_and_format
from app.services.embedding import get_embeddings


async def upload_chat_logs():
    start = time.time()

    with open("data/chat_logs.txt", "r", encoding="utf-8") as f:
        content = f.read()

    # 전략에 따른 파싱 (config.chunking_strategy 기반)
    from app.config import settings
    parsed_lines = parse_and_format(content)
    print(f"파싱된 청크: {len(parsed_lines)}건 (전략: {settings.chunking_strategy})")

    doc_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    add_document(doc_id, {
        "filename": "chat_logs.txt",
        "total_chunks": len(parsed_lines),
        "created_at": created_at,
    })

    # 배치 임베딩 + 저장
    batch_size = 50
    total_stored = 0

    for i in range(0, len(parsed_lines), batch_size):
        batch = parsed_lines[i : i + batch_size]

        texts = [item["embedding_text"] for item in batch]
        embeddings = await get_embeddings(texts)

        chunk_ids = [f"{doc_id}_line_{i + j}" for j in range(len(batch))]
        documents = [item["embedding_text"] for item in batch]
        metadatas = [
            {
                "document_id": doc_id,
                "chunk_index": i + j,
                "filename": "chat_logs.txt",
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

        total_stored += len(batch)
        elapsed = time.time() - start
        pct = total_stored / len(parsed_lines) * 100
        print(f"  [{total_stored}/{len(parsed_lines)}] {pct:.0f}% ({elapsed:.0f}초)")

    elapsed = time.time() - start
    print(f"\n완료! {total_stored}건 저장, 소요: {elapsed:.0f}초")


if __name__ == "__main__":
    asyncio.run(upload_chat_logs())
