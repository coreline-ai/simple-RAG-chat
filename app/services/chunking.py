"""텍스트 분할(Chunking) 서비스

채팅 로그 형식: [날짜, 시간, 채팅방이름, 입력내용, 사용자]
정형 데이터의 구조를 활용하여 다양한 청킹 전략을 지원한다.

전략:
  - line: 1줄 = 1임베딩 (기본)
  - session: 동일 채팅방+시간 근접 메시지를 대화 세션으로 묶음
  - kss: KSS 문장 분리 적용 (긴 메시지만)
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.config import settings


def parse_chat_line(line: str) -> dict | None:
    """채팅 로그 한 줄을 파싱하여 딕셔너리로 반환"""
    line = line.strip()
    if not line:
        return None

    if not (line.startswith("[") and line.endswith("]")):
        return None

    body = line[1:-1]
    parts = body.split(",", maxsplit=2)
    if len(parts) != 3:
        return None

    date_part, time_part, remainder = [part.strip() for part in parts]
    room_and_content = remainder.split(",", maxsplit=1)
    if len(room_and_content) != 2:
        return None

    room, content_and_user = [part.strip() for part in room_and_content]
    content_and_user_parts = content_and_user.rsplit(",", maxsplit=1)
    if len(content_and_user_parts) != 2:
        return None

    content, user = [part.strip() for part in content_and_user_parts]
    if not all([date_part, time_part, room, content, user]):
        return None

    return {
        "date": date_part,
        "time": time_part,
        "room": room,
        "content": content,
        "user": user,
    }


# === KSS 한국어 문장 분리 ===

def _split_long_content(content: str) -> list[str]:
    """긴 메시지를 KSS로 문장 분리

    kss_min_length 미만이면 분리하지 않는다.
    분리된 문장이 너무 짧으면 다시 합친다 (최소 40자).
    """
    if len(content) < settings.kss_min_length:
        return [content]

    try:
        from kss import split_sentences
        sentences = split_sentences(content, backend="pecab")
    except Exception:
        return [content]

    if len(sentences) <= 1:
        return [content]

    # 짧은 문장은 합침 (최소 40자)
    min_chunk = 40
    merged: list[str] = []
    buffer = ""
    for sent in sentences:
        if buffer and len(buffer) + len(sent) > min_chunk:
            merged.append(buffer)
            buffer = sent
        else:
            buffer = (buffer + " " + sent).strip() if buffer else sent
    if buffer:
        merged.append(buffer)

    return merged if merged else [content]


# === 전략 1: 라인 단위 (기본) ===

def parse_and_format_lines(text: str) -> list[dict]:
    """채팅 로그를 라인 단위로 파싱하여 임베딩용 데이터 생성

    1줄 = 1임베딩. KSS 분할이 활성화되면 긴 메시지만 추가 분할한다.
    """
    lines = text.strip().split("\n")
    results = []
    use_kss = settings.chunking_strategy == "kss"

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parsed = parse_chat_line(line)
        if not parsed:
            continue

        if use_kss:
            # 긴 메시지만 KSS 분할
            sub_contents = _split_long_content(parsed["content"])
            for split_idx, sub_content in enumerate(sub_contents):
                embedding_text = f"{parsed['room']} {parsed['user']}: {sub_content}"
                results.append({
                    "embedding_text": embedding_text,
                    "original": line,
                    "metadata": {
                        "room": parsed["room"],
                        "user": parsed["user"],
                        "date": parsed["date"],
                        "date_int": int(parsed["date"].replace("-", "")),
                        "time": parsed["time"],
                        "split_index": split_idx,
                    },
                })
        else:
            embedding_text = f"{parsed['room']} {parsed['user']}: {parsed['content']}"
            results.append({
                "embedding_text": embedding_text,
                "original": line,
                "metadata": {
                    "room": parsed["room"],
                    "user": parsed["user"],
                    "date": parsed["date"],
                    "date_int": int(parsed["date"].replace("-", "")),
                    "time": parsed["time"],
                },
            })

    return results


# === 전략 2: 대화 세션 단위 ===

def parse_and_format_sessions(text: str) -> list[dict]:
    """동일 채팅방 + 시간 근접 메시지를 대화 세션으로 묶어 임베딩

    스킬 원칙: "Row는 문장이 아니라 사건이다"
    → 시간적으로 인접한 메시지를 하나의 사건(세션)으로 묶어 맥락을 보강한다.
    """
    lines = text.strip().split("\n")
    parsed_all: list[dict] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        parsed = parse_chat_line(line)
        if parsed:
            parsed["_original"] = line
            parsed_all.append(parsed)

    if not parsed_all:
        return []

    gap_minutes = settings.session_gap_minutes
    max_lines = settings.session_max_lines

    # (room, date) 기준 그룹핑
    groups: dict[tuple[str, str], list[dict]] = {}
    for p in parsed_all:
        key = (p["room"], p["date"])
        groups.setdefault(key, []).append(p)

    results = []

    for (room, date), messages in groups.items():
        # 시간순 정렬
        messages.sort(key=lambda x: x["time"])

        sessions: list[list[dict]] = []
        current_session: list[dict] = [messages[0]]

        for msg in messages[1:]:
            prev_time = _parse_time(current_session[-1]["time"])
            curr_time = _parse_time(msg["time"])

            if (
                curr_time - prev_time <= timedelta(minutes=gap_minutes)
                and len(current_session) < max_lines
            ):
                current_session.append(msg)
            else:
                sessions.append(current_session)
                current_session = [msg]

        sessions.append(current_session)

        # 각 세션을 임베딩 단위로 변환
        for session in sessions:
            time_start = session[0]["time"]
            time_end = session[-1]["time"]
            users = sorted(set(m["user"] for m in session))

            # 세션 임베딩 텍스트
            lines_text = "\n".join(
                f"{m['user']}: {m['content']}" for m in session
            )
            embedding_text = f"{room} [{time_start}~{time_end}]\n{lines_text}"

            # 원본 보존
            originals = "\n".join(m["_original"] for m in session)

            results.append({
                "embedding_text": embedding_text,
                "original": originals,
                "metadata": {
                    "room": room,
                    "user": ",".join(users),
                    "date": date,
                    "date_int": int(date.replace("-", "")),
                    "time": time_start,
                    "time_end": time_end,
                    "message_count": len(session),
                },
            })

    return results


def _parse_time(time_str: str) -> timedelta:
    """시간 문자열(HH:MM:SS)을 timedelta로 변환"""
    parts = time_str.split(":")
    h = int(parts[0]) if len(parts) > 0 else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return timedelta(hours=h, minutes=m, seconds=s)


# === 통합 진입점 ===

def parse_and_format(text: str) -> list[dict]:
    """설정에 따라 적절한 청킹 전략을 선택하여 실행

    config.chunking_strategy 값에 따라 분기:
      - "line": 1줄 = 1임베딩 (기본)
      - "session": 대화 세션 단위
      - "kss": 라인 단위 + KSS 문장 분리
    """
    strategy = settings.chunking_strategy

    if strategy == "session":
        return parse_and_format_sessions(text)
    else:
        # "line" 또는 "kss" 모두 parse_and_format_lines가 처리
        return parse_and_format_lines(text)


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
