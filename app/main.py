"""FastAPI 애플리케이션 진입점"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.documents import router as documents_router
from app.api.query import router as query_router

app = FastAPI(
    title="RAG-Text-LLM",
    description="지식 기반 QA를 위한 RAG 시스템 (Ollama + ChromaDB)",
    version="0.1.0",
)

# CORS 허용 (로컬 개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(documents_router)
app.include_router(query_router)

# 정적 파일 서빙
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", tags=["상태"])
async def root():
    """채팅 UI 페이지"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/health", tags=["상태"])
async def health_check():
    """서버 상태 확인"""
    return {"status": "ok", "service": "RAG-Text-LLM"}
