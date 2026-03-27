"""채팅 로그 파서

형식: [날짜, 시간, 채팅방이름, 입력내용, 사용자]
기존 chunking.py의 핵심 로직을 클래스로 캡슐화한다.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.config import settings
from app.services.parsers.base import BaseParser


class ChatLogParser(BaseParser):
    """채팅 로그 (.txt) 파서"""

    def detect(self, filename: str) -> bool:
        return filename.endswith(".txt")

    def parse(
        self,
        source: Any,
        *,
        strategy: str | None = None,
        session_gap_minutes: int | None = None,
        session_max_lines: int | None = None,
    ) -> list[dict]:
        """텍스트를 파싱하여 청크 리스트 반환

        Args:
            source: 파싱할 텍스트
            strategy: 청킹 전략 오버라이드. None이면 설정값 사용.
            session_gap_minutes: 세션 간격(분) 오버라이드. None이면 설정값 사용.
            session_max_lines: 세션 최대 라인 수 오버라이드. None이면 설정값 사용.
        """
        text = str(source)
        strategy = strategy if strategy is not None else settings.chunking_strategy

        if strategy == "session":
            return self._parse_sessions(
                text,
                gap_minutes=(
                    session_gap_minutes
                    if session_gap_minutes is not None
                    else settings.session_gap_minutes
                ),
                max_lines=(
                    session_max_lines
                    if session_max_lines is not None
                    else settings.session_max_lines
                ),
            )
        else:
            return self._parse_lines(text, strategy=strategy)

    # === 라인 단위 파싱 ===

    def _parse_lines(self, text: str, *, strategy: str | None = None) -> list[dict]:
        lines = text.strip().split("\n")
        results = []
        selected_strategy = strategy if strategy is not None else settings.chunking_strategy
        use_kss = selected_strategy == "kss"

        for line in lines:
            line = line.strip()
            if not line:
                continue

            parsed = parse_chat_line(line)
            if not parsed:
                continue

            if use_kss:
                sub_contents = _split_long_content(parsed["content"])
                for split_idx, sub_content in enumerate(sub_contents):
                    embedding_text = f"{parsed['room']} {parsed['user']}: {sub_content}"
                    results.append({
                        "embedding_text": embedding_text,
                        "original": line,
                        "metadata": {
                            "doc_type": "chat",
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
                        "doc_type": "chat",
                        "room": parsed["room"],
                        "user": parsed["user"],
                        "date": parsed["date"],
                        "date_int": int(parsed["date"].replace("-", "")),
                        "time": parsed["time"],
                    },
                })

        return results

    # === 세션 단위 파싱 ===

    def _parse_sessions(
        self, text: str, *, gap_minutes: int | None = None, max_lines: int | None = None,
    ) -> list[dict]:
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

        gap_minutes = gap_minutes if gap_minutes is not None else settings.session_gap_minutes
        max_lines = max_lines if max_lines is not None else settings.session_max_lines

        groups: dict[tuple[str, str], list[dict]] = {}
        for p in parsed_all:
            key = (p["room"], p["date"])
            groups.setdefault(key, []).append(p)

        results = []

        for (room, date), messages in groups.items():
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

            for session in sessions:
                time_start = session[0]["time"]
                time_end = session[-1]["time"]
                users = sorted(set(m["user"] for m in session))

                lines_text = "\n".join(f"{m['user']}: {m['content']}" for m in session)
                embedding_text = f"{room} [{time_start}~{time_end}]\n{lines_text}"
                originals = "\n".join(m["_original"] for m in session)

                results.append({
                    "embedding_text": embedding_text,
                    "original": originals,
                    "metadata": {
                        "doc_type": "chat",
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


# === 유틸리티 함수 (chunking.py에서도 사용) ===

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


def _split_long_content(content: str) -> list[str]:
    """긴 메시지를 KSS로 문장 분리"""
    if len(content) < settings.kss_min_length:
        return [content]

    try:
        from kss import split_sentences
        sentences = split_sentences(content, backend="pecab")
    except Exception:
        return [content]

    if len(sentences) <= 1:
        return [content]

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


def _parse_time(time_str: str) -> timedelta:
    """시간 문자열(HH:MM:SS)을 timedelta로 변환"""
    parts = time_str.split(":")
    h = int(parts[0]) if len(parts) > 0 else 0
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return timedelta(hours=h, minutes=m, seconds=s)
