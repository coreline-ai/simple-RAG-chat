"""LLM 서비스 - Ollama qwen2.5-coder:7b 연동

Ollama HTTP API를 통해 로컬 LLM으로 답변을 생성한다.
"""
from abc import ABC, abstractmethod

import httpx

from app.config import settings

# RAG 프롬프트 템플릿
RAG_PROMPT_TEMPLATE = """다음은 채팅 로그에서 검색된 관련 내용입니다.
이 내용을 참고하여 사용자의 질문에 한글로 정확하게 답변해주세요.
검색된 내용에 없는 정보는 추측하지 마세요.

=== 검색된 컨텍스트 ===
{context}
========================

질문: {prompt}

답변:"""


class BaseLLM(ABC):
    """LLM 추상 기본 클래스"""

    @abstractmethod
    async def generate(self, prompt: str, context: str) -> str:
        ...


class OllamaLLM(BaseLLM):
    """Ollama 기반 LLM 구현체"""

    def __init__(self, model: str | None = None):
        self.model = model or settings.llm_model
        self.base_url = settings.ollama_base_url

    async def generate(self, prompt: str, context: str) -> str:
        """컨텍스트 기반 답변 생성

        Args:
            prompt: 사용자 질의
            context: RAG로 검색된 관련 컨텍스트

        Returns:
            생성된 답변 문자열
        """
        full_prompt = RAG_PROMPT_TEMPLATE.format(context=context, prompt=prompt)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                },
                timeout=300.0,
            )
            response.raise_for_status()
            return response.json()["response"]


# 현재 사용할 LLM 인스턴스
llm = OllamaLLM()
