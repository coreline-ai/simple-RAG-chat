"""애플리케이션 환경 설정"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama 설정 (기존, 하위 호환성 유지)
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5-coder:7b"
    embedding_model: str = "bge-m3"

    # LLM 제공자 설정
    # 지원 가능한 값: ollama (기본값), claude, codex
    llm_provider: str = "ollama"

    # CLIProxyAPI 프록시 설정 (claude/codex 사용 시 필요)
    proxy_api_url: str = "http://localhost:8080"
    proxy_api_key: str = ""
    claude_model: str = "claude-sonnet-latest"
    codex_model: str = "gpt-5-codex"

    # 벡터 DB 설정
    vector_db_type: str = "chroma"
    chroma_persist_dir: str = "./chroma_db"

    # 청킹 설정
    chunk_size: int = 20
    chunk_overlap: int = 5
    chunking_strategy: str = "line"  # "line" | "session" | "kss"
    session_gap_minutes: int = 30
    session_max_lines: int = 10
    kss_min_length: int = 80  # 이 길이 이상만 KSS 문장 분할

    # 쿼리 분석 설정
    use_kiwi_keywords: bool = True  # kiwipiepy 형태소 분석 키워드 추출

    # 임베딩 캐시
    embedding_cache_enabled: bool = True

    # 엑셀 이슈 데이터 설정
    excel_row_max_chars: int = 900  # 이 길이 초과 시 2차 KSS 분할
    excel_sheet_name: str = ""      # 빈 값이면 첫 번째 시트
    excel_id_prefix: str = "issue"  # doc_id 접두사

    # 검색 설정
    top_k: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
