"""FastAPI 애플리케이션 진입점"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.documents import router as documents_router
from app.api.query import router as query_router
from app.services.llm import get_llm_status

app = FastAPI(
    title="Simple RAG Chat",
    description="정형 채팅 로그용 RAG 시스템 (FastAPI + ChromaDB + Ollama/Proxy LLM)",
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


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """기본 favicon 요청의 404 로그 방지"""
    return Response(status_code=204)


@app.get("/health", tags=["상태"])
async def health_check():
    """서버 상태 확인"""
    return {"status": "ok", "service": "Simple RAG Chat"}


@app.get("/health/llm", tags=["상태"])
async def llm_health_check():
    """LLM 제공자 연결 상태 확인"""
    status = await get_llm_status()
    return {"status": "ok" if status.get("ok") else "degraded", **status}
