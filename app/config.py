"""애플리케이션 환경 설정"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama 설정
    ollama_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5-coder:7b"
    embedding_model: str = "bge-m3"

    # ChromaDB 설정
    chroma_persist_dir: str = "./chroma_db"

    # 청킹 설정 (라인 수 기준)
    chunk_size: int = 20
    chunk_overlap: int = 5

    # 검색 설정
    top_k: int = 5

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
