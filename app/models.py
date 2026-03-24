"""데이터 모델 (딕셔너리 기반)

ChromaDB 사용으로 SQLAlchemy 모델 대신 딕셔너리 구조를 정의한다.
"""
from datetime import datetime, timezone


def create_document(doc_id: str, filename: str, content: str, total_chunks: int) -> dict:
    """문서 메타데이터 딕셔너리 생성"""
    return {
        "id": doc_id,
        "filename": filename,
        "content": content,
        "total_chunks": total_chunks,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
