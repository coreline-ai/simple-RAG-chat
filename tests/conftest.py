"""pytest 설정 파일 - 커스텀 커맨드 라인 옵션"""
from __future__ import annotations

import os
import sys

import pytest


def pytest_addoption(parser):
    """커스텀 커맨드 라인 옵션 추가"""
    parser.addoption(
        "--run-performance",
        action="store_true",
        default=False,
        help="성능 테스트 실행 (기본값: skip)"
    )


def pytest_collection_modifyitems(config, items):
    """성능 테스트 마커 처리"""
    if config.getoption("--run-performance"):
        return

    skip_performance = pytest.mark.skip(reason="성능 테스트는 --run-performance 옵션으로 실행하세요")
    for item in items:
        if "performance" in item.keywords:
            item.add_marker(skip_performance)


@pytest.fixture(autouse=True)
def _reset_async_singletons():
    """각 테스트 후 asyncio 기반 싱글턴을 리셋하여 이벤트 루프 간 오염 방지"""
    yield
    from app.services.embedding import reset_semaphore
    reset_semaphore()
    from app.services.llm import reset_llm_locks
    reset_llm_locks()


@pytest.fixture
def isolated_db(tmp_path):
    """E2E 테스트를 위한 격리된 DB fixture

    각 테스트마다 독립적인 ChromaDB와 documents.json을 생성합니다.
    """
    # 임시 DB 경로 설정
    temp_db_dir = str(tmp_path / "chroma_db_test")
    os.environ["CHROMA_PERSIST_DIR"] = temp_db_dir

    # 관련 모듈 캐시 삭제
    modules_to_clear = [
        "app.config",
        "app.database",
        "app.services.vector_stores.factory",
        "app.services.vector_stores.chroma_store",
        "app.services.vector_stores.base",
        "app.services.retrieval",
        "app.services.query_analyzer",
        "app.services.embedding_cache",
        "app.services.embedding",
        "app.services.parsers.chat_log_parser",
        "app.services.parsers.excel_issue_parser",
        "app.services.parsers.factory",
        "app.services.parsers",
        "app.services.chunking",
        "app.services.llm",
        "app.api.documents",
        "app.api.query",
        "app.main",
    ]

    # 삭제할 모듈만 저장 (아직 import 안 된 것도 있음)
    cleared_modules = {}
    for mod in modules_to_clear:
        if mod in sys.modules:
            cleared_modules[mod] = sys.modules[mod]
            del sys.modules[mod]

    yield temp_db_dir

    # 테스트 후 모듈 복구 — 순서 의존성 방지
    for mod, original in cleared_modules.items():
        sys.modules[mod] = original

