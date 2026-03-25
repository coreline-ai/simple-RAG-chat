"""텍스트 분할(Chunking) 서비스 — 하위 호환 래퍼

실제 파싱 로직은 parsers/ 패키지로 이동하였다.
기존 import 경로를 유지하기 위해 래퍼 함수를 제공한다.
"""
from __future__ import annotations

from app.config import settings

# 핵심 함수 재수출 (기존 import 호환)
from app.services.parsers.chat_log_parser import (
    ChatLogParser,
    _parse_time,
    _split_long_content,
    parse_chat_line,
)
from app.services.parsers.factory import ParserFactory


def parse_and_format_lines(text: str) -> list[dict]:
    """채팅 로그를 라인 단위로 파싱 (하위 호환 래퍼)"""
    parser = ChatLogParser()
    # 강제 line 전략
    original = settings.chunking_strategy
    try:
        settings.chunking_strategy = "line"
        return parser.parse(text)
    finally:
        settings.chunking_strategy = original


def parse_and_format_sessions(text: str) -> list[dict]:
    """채팅 로그를 세션 단위로 파싱 (하위 호환 래퍼)"""
    parser = ChatLogParser()
    original = settings.chunking_strategy
    try:
        settings.chunking_strategy = "session"
        return parser.parse(text)
    finally:
        settings.chunking_strategy = original


def parse_and_format(text: str) -> list[dict]:
    """설정에 따라 적절한 청킹 전략을 선택 (하위 호환 래퍼)

    채팅 로그 전용. 엑셀 등 다른 형식은 ParserFactory 사용.
    """
    parser = ChatLogParser()
    return parser.parse(text)


# === 하위 호환용 (기존 테스트 유지) ===

def chunk_text(text: str, chunk_size: int | None = None, chunk_overlap: int | None = None) -> list[str]:
    """텍스트를 지정된 크기의 청크로 분할 (하위 호환용)"""
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap

    lines = [line for line in text.strip().split("\n") if line.strip()]
    if not lines:
        return []

    chunks = []
    start = 0
    while start < len(lines):
        end = min(start + chunk_size, len(lines))
        chunk = "\n".join(lines[start:end])
        chunks.append(chunk)
        start += chunk_size - chunk_overlap
        if start >= len(lines):
            break

    return chunks


def chunk_chat_by_room(text: str, chunk_size: int | None = None) -> list[str]:
    """채팅방별로 그룹핑한 뒤 청크로 분할 (하위 호환용)"""
    chunk_size = chunk_size or settings.chunk_size
    lines = [line for line in text.strip().split("\n") if line.strip()]

    rooms: dict[str, list[str]] = {}
    for line in lines:
        parsed = parse_chat_line(line)
        if parsed:
            rooms.setdefault(parsed["room"], []).append(line)

    chunks = []
    for room, room_lines in rooms.items():
        for i in range(0, len(room_lines), chunk_size):
            chunk = "\n".join(room_lines[i : i + chunk_size])
            chunks.append(chunk)

    return chunks
