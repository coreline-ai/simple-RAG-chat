"""E2E (End-to-End) 테스트 - 전체 파이프라인 검증

문서 업로드 → 임베딩 → 저장 → 검색 → 답변 생성 전체 흐름 테스트

주의: 이 테스트는 실제 ChromaDB를 생성하므로 tmp_path를 사용합니다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

# === E2E 테스트 유틸리티 ===

def _create_mock_embedding_service():
    """임베딩 서비스 mock 생성"""
    mock_emb = Mock()

    # get_embedding mock
    async def mock_get_embedding(text: str) -> list[float]:
        # 텍스트 해시 기반 고정 임베딩 반환
        hash_val = hash(text) % 100
        return [0.1, 0.2, 0.3, hash_val / 100]

    # get_embeddings mock
    async def mock_get_embeddings(texts: list[str]) -> list[list[float]]:
        return [await mock_get_embedding(t) for t in texts]

    mock_emb.get_embedding = mock_get_embedding
    mock_emb.get_embeddings = mock_get_embeddings
    return mock_emb


def _create_mock_llm_service():
    """LLM 서비스 mock 생성"""
    mock_llm = AsyncMock()

    async def mock_generate(prompt: str, context: list[dict]) -> str:
        # 컨텍스트 기반 간단 답변 생성
        if context:
            sources = [c.get("content", "")[:50] for c in context[:2]]
            return f"검색 결과: {', '.join(sources)}"
        return "관련 정보를 찾을 수 없습니다."

    mock_llm.generate = mock_generate
    return mock_llm


# === E2E 테스트 ===

@pytest.mark.asyncio
async def test_e2e_health_엔드포인트_동작():
    """상태 확인 엔드포인트 테스트 - 가장 간단한 E2E 테스트"""
    # 이 테스트는 외부 서비스 mock 없이 동작 확인
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 기본 상태 확인
    response = client.get("/health")
    assert response.status_code == 200
    health = response.json()
    assert "status" in health
    assert health["status"] == "ok"

    # LLM 상태 확인
    response = client.get("/health/llm")
    assert response.status_code == 200
    llm_health = response.json()
    assert "provider" in llm_health
    assert "configured_model" in llm_health


@pytest.mark.asyncio
async def test_e2e_임베딩_서비스_mock로_문서_업로드_및_검색(monkeypatch, isolated_db):
    """문서 업로드 → 임베딩 → 저장 → 검색 전체 파이프라인 (mock 사용)"""
    import sys
    import os
    import shutil

    # 모듈 캐시 삭제 (다시 import하기 위해)
    for mod in list(sys.modules.keys()):
        if mod.startswith("app."):
            del sys.modules[mod]

    # 환경 변수 설정
    os.environ["CHROMA_PERSIST_DIR"] = isolated_db

    from fastapi.testclient import TestClient
    from app.main import app

    # 외부 서비스 mock
    mock_emb = _create_mock_embedding_service()
    mock_llm = _create_mock_llm_service()

    monkeypatch.setattr("app.services.embedding.get_embedding", mock_emb.get_embedding)
    monkeypatch.setattr("app.services.embedding.get_embeddings", mock_emb.get_embeddings)
    monkeypatch.setattr("app.services.llm.OllamaLLM.generate", mock_llm.generate)

    client = TestClient(app)

    # 1단계: 문서 업로드 (텍스트)
    chat_log = """[2024-03-01, 10:00:00, 개발팀, 서버 배포 완료, 김민수]
[2024-03-01, 10:05:00, 개발팀, 데이터베이스 백업 완료, 박서준]"""

    response = client.post(
        "/documents",
        json={"content": chat_log, "filename": "test_chat.txt"}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == "test_chat.txt"
    assert data["total_chunks"] == 2

    doc_id = data["id"]
    assert doc_id is not None

    # 2단계: 문서 목록 확인
    response = client.get("/documents")
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 1
    assert len(result["documents"]) == 1
    assert result["documents"][0]["id"] == doc_id

    # 3단계: 검색
    response = client.post(
        "/query",
        json={"question": "서버 배포 관련 내용", "top_k": 2}
    )

    assert response.status_code == 200
    result = response.json()
    assert "answer" in result
    assert "sources" in result

    # 4단계: 문서 삭제
    response = client.delete(f"/documents/{doc_id}")
    assert response.status_code == 204


@pytest.mark.asyncio
async def test_e2e_빈_컬렉션에서_검색시_빈_결과_반환(monkeypatch, isolated_db):
    """빈 컬렉션에서 검색 시 빈 결과 반환"""
    import sys
    import os

    # 모듈 캐시 삭제
    for mod in list(sys.modules.keys()):
        if mod.startswith("app."):
            del sys.modules[mod]

    os.environ["CHROMA_PERSIST_DIR"] = isolated_db

    from fastapi.testclient import TestClient
    from app.main import app

    mock_emb = _create_mock_embedding_service()
    mock_llm = _create_mock_llm_service()

    monkeypatch.setattr("app.services.embedding.get_embedding", mock_emb.get_embedding)
    monkeypatch.setattr("app.services.embedding.get_embeddings", mock_emb.get_embeddings)
    monkeypatch.setattr("app.services.llm.OllamaLLM.generate", mock_llm.generate)

    client = TestClient(app)

    # 문서 없이 검색
    response = client.post(
        "/query",
        json={"question": "아무 내용", "top_k": 5}
    )

    assert response.status_code == 200
    result = response.json()
    assert result["sources"] == []
    assert "answer" in result


@pytest.mark.asyncio
async def test_e2e_문서_상세_조회_및_404_처리(monkeypatch, isolated_db):
    """문서 상세 조회 및 없는 문서 404 처리"""
    import sys
    import os

    # 모듈 캐시 삭제
    for mod in list(sys.modules.keys()):
        if mod.startswith("app."):
            del sys.modules[mod]

    os.environ["CHROMA_PERSIST_DIR"] = isolated_db

    from fastapi.testclient import TestClient
    from app.main import app

    mock_emb = _create_mock_embedding_service()

    monkeypatch.setattr("app.services.embedding.get_embedding", mock_emb.get_embedding)
    monkeypatch.setattr("app.services.embedding.get_embeddings", mock_emb.get_embeddings)

    client = TestClient(app)

    # 문서 업로드
    response = client.post(
        "/documents",
        json={"content": "[2024-03-01, 10:00:00, 개발팀, 테스트 메시지, 김민수]", "filename": "test.txt"}
    )
    assert response.status_code == 201
    doc_id = response.json()["id"]

    # 문서 상세 조회
    response = client.get(f"/documents/{doc_id}")
    assert response.status_code == 200
    doc = response.json()
    assert doc["id"] == doc_id
    assert doc["filename"] == "test.txt"

    # 없는 문서 조회
    response = client.get("/documents/nonexistent-id")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_e2e_여러_문서_업로드_후_검색_결과_통합(monkeypatch, isolated_db):
    """여러 문서 업로드 후 검색 결과가 통합되는지 확인"""
    import sys
    import os

    # 모듈 캐시 삭제
    for mod in list(sys.modules.keys()):
        if mod.startswith("app."):
            del sys.modules[mod]

    os.environ["CHROMA_PERSIST_DIR"] = isolated_db

    from fastapi.testclient import TestClient
    from app.main import app

    mock_emb = _create_mock_embedding_service()
    mock_llm = _create_mock_llm_service()

    monkeypatch.setattr("app.services.embedding.get_embedding", mock_emb.get_embedding)
    monkeypatch.setattr("app.services.embedding.get_embeddings", mock_emb.get_embeddings)
    monkeypatch.setattr("app.services.llm.OllamaLLM.generate", mock_llm.generate)

    client = TestClient(app)

    # 문서 1 업로드
    response = client.post(
        "/documents",
        json={"content": "[2024-03-01, 10:00:00, 개발팀, API 개발, 김민수]", "filename": "doc1.txt"}
    )
    assert response.status_code == 201

    # 문서 2 업로드
    response = client.post(
        "/documents",
        json={"content": "[2024-03-02, 14:00:00, 개발팀, API 테스트, 박서준]", "filename": "doc2.txt"}
    )
    assert response.status_code == 201

    # 전체 문서 확인
    response = client.get("/documents")
    result = response.json()
    assert result["total"] == 2
    assert len(result["documents"]) == 2

    # 검색
    response = client.post(
        "/query",
        json={"question": "API 관련 작업", "top_k": 5}
    )

    assert response.status_code == 200
    result = response.json()
    assert len(result["sources"]) >= 1
