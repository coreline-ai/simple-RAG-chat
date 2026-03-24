"""청킹 서비스 단위 테스트"""
import pytest

from app.services.chunking import chunk_text, parse_chat_line, chunk_chat_by_room


class TestParseChatLine:
    """채팅 로그 파싱 테스트"""

    def test_정상_파싱(self):
        line = "[2024-01-15, 09:30:00, 개발팀, 오늘 회의 3시에 시작합니다, 김민수]"
        result = parse_chat_line(line)
        assert result is not None
        assert result["date"] == "2024-01-15"
        assert result["time"] == "09:30:00"
        assert result["room"] == "개발팀"
        assert result["content"] == "오늘 회의 3시에 시작합니다"
        assert result["user"] == "김민수"

    def test_빈_줄(self):
        assert parse_chat_line("") is None
        assert parse_chat_line("   ") is None

    def test_잘못된_형식(self):
        assert parse_chat_line("이것은 일반 텍스트") is None
        assert parse_chat_line("[불완전한 데이터]") is None


class TestChunkText:
    """텍스트 분할 테스트"""

    def test_기본_분할(self):
        # 10줄 텍스트를 3줄씩 분할 (오버랩 1)
        lines = [f"[2024-01-01, 00:00:0{i}, 테스트, 메시지{i}, 사용자]" for i in range(10)]
        text = "\n".join(lines)
        chunks = chunk_text(text, chunk_size=3, chunk_overlap=1)
        assert len(chunks) > 0
        # 첫 청크는 3줄
        assert chunks[0].count("\n") == 2

    def test_빈_텍스트(self):
        assert chunk_text("") == []
        assert chunk_text("   \n  \n  ") == []

    def test_오버랩_적용(self):
        lines = [f"줄{i}" for i in range(10)]
        text = "\n".join(lines)
        chunks = chunk_text(text, chunk_size=5, chunk_overlap=2)
        # 오버랩이 있으므로 인접 청크 간 겹치는 내용 존재
        assert len(chunks) >= 2
        # 두 번째 청크에 첫 번째 청크의 마지막 2줄이 포함
        first_lines = chunks[0].split("\n")
        second_lines = chunks[1].split("\n")
        assert first_lines[-2:] == second_lines[:2]

    def test_작은_텍스트는_단일_청크(self):
        text = "한줄\n두줄"
        chunks = chunk_text(text, chunk_size=100, chunk_overlap=10)
        assert len(chunks) == 1


class TestChunkChatByRoom:
    """채팅방별 분할 테스트"""

    def test_채팅방별_그룹핑(self):
        lines = [
            "[2024-01-01, 09:00:00, 개발팀, 안녕하세요, 김민수]",
            "[2024-01-01, 09:01:00, 마케팅팀, 회의합시다, 이지영]",
            "[2024-01-01, 09:02:00, 개발팀, 네 알겠습니다, 박서준]",
        ]
        text = "\n".join(lines)
        chunks = chunk_chat_by_room(text, chunk_size=100)
        # 2개 채팅방이므로 최소 2개 청크
        assert len(chunks) == 2

    def test_빈_입력(self):
        assert chunk_chat_by_room("") == []
