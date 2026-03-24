"""텍스트 분할(Chunking) 서비스

채팅 로그 형식: [날짜, 시간, 채팅방이름, 입력내용, 사용자]
정형 데이터의 구조를 활용하여 1줄 = 1임베딩 + 메타데이터로 처리한다.
"""
import re

from app.config import settings


def parse_chat_line(line: str) -> dict | None:
    """채팅 로그 한 줄을 파싱하여 딕셔너리로 반환"""
    line = line.strip()
    if not line:
        return None

    match = re.match(
        r"\[(\d{4}-\d{2}-\d{2}),\s*(\d{2}:\d{2}:\d{2}),\s*(.+?),\s*(.+?),\s*(.+?)\]",
        line,
    )
    if not match:
        return None

    return {
        "date": match.group(1),
        "time": match.group(2),
        "room": match.group(3).strip(),
        "content": match.group(4).strip(),
        "user": match.group(5).strip(),
    }


def parse_and_format_lines(text: str) -> list[dict]:
    """채팅 로그를 라인 단위로 파싱하여 임베딩용 데이터 생성

    각 라인을 개별 임베딩 단위로 변환한다.
    - embedding_text: 검색에 최적화된 텍스트 ("채팅방 사용자: 내용")
    - original: 원본 라인
    - metadata: ChromaDB 메타데이터 필터용 (room, user, date, time)

    Returns:
        파싱된 라인 딕셔너리 리스트
    """
    lines = text.strip().split("\n")
    results = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parsed = parse_chat_line(line)
        if not parsed:
            continue

        # 임베딩용 텍스트: 채팅방+사용자를 포함하여 검색 정확도 향상
        embedding_text = f"{parsed['room']} {parsed['user']}: {parsed['content']}"

        results.append({
            "embedding_text": embedding_text,
            "original": line,
            "metadata": {
                "room": parsed["room"],
                "user": parsed["user"],
                "date": parsed["date"],
                "time": parsed["time"],
            },
        })

    return results


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
