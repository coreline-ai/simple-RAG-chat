"""파서 단위 테스트 - ChatLogParser, ExcelIssueParser, labeler"""
from __future__ import annotations

import pytest

from app.services.parsers.chat_log_parser import ChatLogParser, parse_chat_line


# === 테스트 데이터 ===

CHAT_LOG_SAMPLE = "[2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]"
CHAT_LOG_WITH_COMMA = "[2024-01-15, 09:30:00, 개발팀, 배포가 완료되었습니다, 확인 부탁드립니다, 김민수]"
CHAT_LOG_EMPTY = ""
CHAT_LOG_INVALID = "invalid log format"
CHAT_LOG_NO_BRACKETS = "2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]"


# === P1-4: ChatLogParser 테스트 ===

class TestChatLogParser:
    """ChatLogParser 테스트"""

    def test_detect_txt_파일을_감지한다(self):
        """txt 파일 확장자 감지"""
        parser = ChatLogParser()
        assert parser.detect("test.txt") is True
        assert parser.detect("test.log") is False
        assert parser.detect("test.csv") is False

    def test_detect_빈_문자열은_False를_반환한다(self):
        """빈 파일명은 False 반환"""
        parser = ChatLogParser()
        assert parser.detect("") is False

    # === parse_chat_line 테스트 ===

    def test_parse_chat_line_기본_형식을_파싱한다(self):
        """기본 채팅 로그 파싱"""
        result = parse_chat_line(CHAT_LOG_SAMPLE)

        assert result is not None
        assert result["date"] == "2024-01-15"
        assert result["time"] == "09:30:00"
        assert result["room"] == "개발팀"
        assert result["content"] == "안녕하세요"
        assert result["user"] == "김민수"

    def test_parse_chat_line_쉼표가_포함된_메시지를_파싱한다(self):
        """메시지 본문에 쉼표가 포함된 경우 파싱"""
        result = parse_chat_line(CHAT_LOG_WITH_COMMA)

        assert result is not None
        assert result["content"] == "배포가 완료되었습니다, 확인 부탁드립니다"
        assert result["user"] == "김민수"

    def test_parse_chat_line_빈_문자열은_None을_반환한다(self):
        """빈 문자열은 None 반환"""
        assert parse_chat_line(CHAT_LOG_EMPTY) is None

    def test_parse_chat_line_대괄호가_없으면_None을_반환한다(self):
        """대괄호가 없는 형식은 None 반환"""
        assert parse_chat_line(CHAT_LOG_NO_BRACKETS) is None

    def test_parse_chat_line_잘못된_형식은_None을_반환한다(self):
        """잘못된 형식은 None 반환"""
        assert parse_chat_line(CHAT_LOG_INVALID) is None

    def test_parse_chat_line_공백만_있으면_None을_반환한다(self):
        """공백만 있는 문자열은 None 반환"""
        assert parse_chat_line("   ") is None
        assert parse_chat_line("\n\t") is None

    # === _parse_lines 테스트 ===

    def test_parse_lines_단일_라인을_파싱한다(self, monkeypatch):
        """단일 라인 파싱"""
        monkeypatch.setattr("app.services.parsers.chat_log_parser.settings", type("Settings", (), {
            "chunking_strategy": "line",
        })())

        parser = ChatLogParser()
        text = CHAT_LOG_SAMPLE
        results = parser.parse(text)

        assert len(results) == 1
        assert results[0]["embedding_text"] == "개발팀 김민수: 안녕하세요"
        assert results[0]["original"] == CHAT_LOG_SAMPLE
        assert results[0]["metadata"]["room"] == "개발팀"
        assert results[0]["metadata"]["user"] == "김민수"
        assert results[0]["metadata"]["date"] == "2024-01-15"
        assert results[0]["metadata"]["date_int"] == 20240115

    def test_parse_lines_여러_라인을_파싱한다(self, monkeypatch):
        """여러 라인 파싱"""
        monkeypatch.setattr("app.services.parsers.chat_log_parser.settings", type("Settings", (), {
            "chunking_strategy": "line",
        })())

        parser = ChatLogParser()
        text = f"{CHAT_LOG_SAMPLE}\n{CHAT_LOG_WITH_COMMA}"
        results = parser.parse(text)

        assert len(results) == 2
        # embedding_text 확인
        assert "안녕하세요" in results[0]["embedding_text"]
        assert "배포가 완료되었습니다, 확인 부탁드립니다" in results[1]["embedding_text"]

    def test_parse_lines_빈_라인은_무시한다(self, monkeypatch):
        """빈 라인은 무시"""
        monkeypatch.setattr("app.services.parsers.chat_log_parser.settings", type("Settings", (), {
            "chunking_strategy": "line",
        })())

        parser = ChatLogParser()
        text = f"{CHAT_LOG_SAMPLE}\n\n\n{CHAT_LOG_WITH_COMMA}"
        results = parser.parse(text)

        assert len(results) == 2

    def test_parse_lines_잘못된_형식은_무시한다(self, monkeypatch):
        """잘못된 형식의 라인은 무시"""
        monkeypatch.setattr("app.services.parsers.chat_log_parser.settings", type("Settings", (), {
            "chunking_strategy": "line",
        })())

        parser = ChatLogParser()
        text = f"{CHAT_LOG_SAMPLE}\n{CHAT_LOG_INVALID}\n{CHAT_LOG_WITH_COMMA}"
        results = parser.parse(text)

        assert len(results) == 2

    def test_parse_lines_date_int를_생성한다(self, monkeypatch):
        """date_int 메타데이터 생성 확인"""
        monkeypatch.setattr("app.services.parsers.chat_log_parser.settings", type("Settings", (), {
            "chunking_strategy": "line",
        })())

        parser = ChatLogParser()
        results = parser.parse(CHAT_LOG_SAMPLE)

        assert results[0]["metadata"]["date_int"] == 20240115

    def test_parse_lines_kss_strategy_override를_적용한다(self, monkeypatch):
        """strategy='kss' 전달 시 settings와 무관하게 문장 분할을 적용"""
        import app.services.parsers.chat_log_parser as chat_log_parser

        monkeypatch.setattr(chat_log_parser, "settings", type("Settings", (), {
            "chunking_strategy": "line",
            "kss_min_length": 1,
        })())
        monkeypatch.setattr(chat_log_parser, "_split_long_content", lambda content: ["첫 문장", "둘째 문장"])

        parser = chat_log_parser.ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 긴 문장입니다. 둘째 문장입니다., 김민수]"

        results = parser.parse(text, strategy="kss")

        assert len(results) == 2
        assert results[0]["metadata"]["split_index"] == 0
        assert results[1]["metadata"]["split_index"] == 1

    # === _parse_sessions 테스트 ===

    def test_parse_sessions_단일_메시지를_하나의_세션으로_처리한다(self):
        """단일 메시지는 하나의 세션"""
        parser = ChatLogParser()
        results = parser.parse(CHAT_LOG_SAMPLE, strategy="session", session_gap_minutes=30, session_max_lines=100)

        assert len(results) == 1
        assert results[0]["metadata"]["message_count"] == 1

    def test_parse_sessions_연속된_메시지를_하나의_세션으로_처리한다(self):
        """연속된 메시지는 하나의 세션으로 처리"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]\n[2024-01-15, 09:31:00, 개발팀, 네 반갑습니다, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        assert len(results) == 1
        assert results[0]["metadata"]["message_count"] == 2
        assert "김민수" in results[0]["metadata"]["user"]
        assert "박서준" in results[0]["metadata"]["user"]

    def test_parse_sessions_gap이_크면_세션을_분리한다(self):
        """시간 간격이 크면 세션 분리"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]\n[2024-01-15, 10:05:00, 개발팀, 점심시간 되었네요, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        # 35분 차이 = 세션 분리
        assert len(results) == 2
        assert results[0]["metadata"]["message_count"] == 1
        assert results[1]["metadata"]["message_count"] == 1

    def test_parse_sessions_최대_라인을_초과하면_세션을_분리한다(self):
        """최대 라인 수 초과 시 세션 분리"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 메시지1, 김민수]\n[2024-01-15, 09:31:00, 개발팀, 메시지2, 박서준]\n[2024-01-15, 09:32:00, 개발팀, 메시지3, 이지영]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=2)

        # max_lines=2이므로 3개 메시지는 2개 세션으로 분리
        assert len(results) == 2
        assert results[0]["metadata"]["message_count"] == 2
        assert results[1]["metadata"]["message_count"] == 1

    def test_parse_sessions_다른_방은_별도_세션으로_처리한다(self):
        """다른 채팅방은 별도 세션으로 처리"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]\n[2024-01-15, 09:31:00, 마케팅팀, 반갑습니다, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        # 방이 다르므로 별도 세션
        assert len(results) == 2
        assert results[0]["metadata"]["room"] == "개발팀"
        assert results[1]["metadata"]["room"] == "마케팅팀"

    def test_parse_sessions_다른_날짜는_별도_세션으로_처리한다(self):
        """다른 날짜는 별도 세션으로 처리"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 안녕하세요, 김민수]\n[2024-01-16, 09:30:00, 개발팀, 내일은 16일이네요, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        # 날짜가 다르므로 별도 세션
        assert len(results) == 2
        assert results[0]["metadata"]["date"] == "2024-01-15"
        assert results[1]["metadata"]["date"] == "2024-01-16"

    def test_parse_sessions_time_start와_time_end를_설정한다(self):
        """세션 시간 범위 설정"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 메시지1, 김민수]\n[2024-01-15, 09:45:00, 개발팀, 메시지2, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        assert len(results) == 1
        assert results[0]["metadata"]["time"] == "09:30:00"
        assert results[0]["metadata"]["time_end"] == "09:45:00"

    def test_parse_sessions_original에_모든_원본을_포함한다(self):
        """original 필드에 세션의 모든 원본 라인 포함"""
        parser = ChatLogParser()
        text = "[2024-01-15, 09:30:00, 개발팀, 메시지1, 김민수]\n[2024-01-15, 09:31:00, 개발팀, 메시지2, 박서준]"
        results = parser.parse(text, strategy="session", session_gap_minutes=30, session_max_lines=100)

        assert len(results) == 1
        original = results[0]["original"]
        assert "[2024-01-15, 09:30:00" in original
        assert "[2024-01-15, 09:31:00" in original


# === P1-5: ExcelIssueParser 테스트 ===

class TestExcelIssueParser:
    """ExcelIssueParser 테스트"""

    def test_detect_xlsx_xls_파일을_감지한다(self):
        """xlsx/xls 파일 확장자 감지"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        parser = ExcelIssueParser()
        assert parser.detect("test.xlsx") is True
        assert parser.detect("test.xls") is True
        assert parser.detect("test.txt") is False
        assert parser.detect("test.csv") is False

    # === 날짜 변환 유틸 테스트 ===

    def test_datetime_to_int_datetime을_변환한다(self):
        """datetime 객체를 YYYYMMDD int로 변환"""
        from datetime import datetime
        from app.services.parsers.excel_issue_parser import _datetime_to_int

        dt = datetime(2024, 3, 15, 10, 30)
        result = _datetime_to_int(dt)
        assert result == 20240315

    def test_datetime_to_int_문자열을_변환한다(self):
        """날짜 문자열을 YYYYMMDD int로 변환"""
        from app.services.parsers.excel_issue_parser import _datetime_to_int

        assert _datetime_to_int("2024-03-15") == 20240315
        assert _datetime_to_int("2024/03/15") == 20240315
        assert _datetime_to_int("20240315") == 20240315

    def test_datetime_to_int_None은_0을_반환한다(self):
        """None은 0 반환"""
        from app.services.parsers.excel_issue_parser import _datetime_to_int

        assert _datetime_to_int(None) == 0

    def test_datetime_to_int_잘못된_형식은_0을_반환한다(self):
        """잘못된 형식은 0 반환"""
        from app.services.parsers.excel_issue_parser import _datetime_to_int

        assert _datetime_to_int("invalid") == 0

    def test_format_date_datetime을_문자열로_변환한다(self):
        """datetime을 YYYY-MM-DD 문자열로 변환"""
        from datetime import datetime
        from app.services.parsers.excel_issue_parser import _format_date

        dt = datetime(2024, 3, 15, 10, 30)
        result = _format_date(dt)
        assert result == "2024-03-15"

    def test_format_date_문자열은_그대로_반환한다(self):
        """문자열은 그대로 반환"""
        from app.services.parsers.excel_issue_parser import _format_date

        assert _format_date("2024-03-15") == "2024-03-15"
        assert _format_date("  2024-03-15  ") == "2024-03-15"

    def test_format_date_None은_빈_문자열을_반환한다(self):
        """None은 빈 문자열 반환"""
        from app.services.parsers.excel_issue_parser import _format_date

        assert _format_date(None) == ""

    def test_safe_str_None을_변환한다(self):
        """None을 빈 문자열로 변환"""
        from app.services.parsers.excel_issue_parser import _safe_str

        assert _safe_str(None) == ""

    def test_safe_str_문자열을_trim_반환한다(self):
        """문자열 양쪽 공백 제거"""
        from app.services.parsers.excel_issue_parser import _safe_str

        assert _safe_str("  test  ") == "test"

    def test_safe_str_숫자를_문자열로_변환한다(self):
        """숫자를 문자열로 변환"""
        from app.services.parsers.excel_issue_parser import _safe_str

        assert _safe_str(123) == "123"

    # === _build_metadata 테스트 ===

    def test_build_metadata_모든_날짜_형식을_생성한다(self, monkeypatch):
        """날짜 3형식 (iso/int/하위호환) 생성 확인"""
        from datetime import datetime
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
        })())

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족",
            "created_at": datetime(2024, 3, 15),
            "assignee": "Sujin",
            "status": "진행",
            "start_at": datetime(2024, 3, 16),
            "due_at": datetime(2024, 3, 20),
            "completed_at": None,
        }

        metadata = parser._build_metadata(row, "issue_000001")

        assert metadata["doc_type"] == "issue"
        assert metadata["doc_id"] == "issue_000001"
        assert metadata["title"] == "GPU 메모리 부족"
        assert metadata["assignee"] == "Sujin"
        assert metadata["status"] == "진행"
        # 날짜 3형식
        assert metadata["created_at_iso"] == "2024-03-15"
        assert metadata["created_at_int"] == 20240315
        assert metadata["start_at_int"] == 20240316
        assert metadata["due_at_int"] == 20240320
        assert metadata["completed_at_int"] == 0
        # 하위 호환
        assert metadata["date"] == "2024-03-15"
        assert metadata["date_int"] == 20240315

    # === _extract_row 테스트 ===

    def test_extract_row_title이_없으면_None을_반환한다(self, monkeypatch):
        """title이 없으면 None 반환"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
        })())

        parser = ExcelIssueParser()
        row = ("", "2024-03-15", "확인 내용")  # title이 비어있음
        col_indices = {"title": 0, "created_at": 1, "basic_check": 2}

        result = parser._extract_row(row, col_indices)
        assert result is None

    def test_extract_row_유효한_행을_추출한다(self, monkeypatch):
        """유효한 행 추출"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
        })())

        parser = ExcelIssueParser()
        row = ("GPU 메모리 부족", "2024-03-15", "확인 내용", "작업 내용", "지시", "Sujin")
        col_indices = {
            "title": 0,
            "created_at": 1,
            "basic_check": 2,
            "basic_work": 3,
            "instruction": 4,
            "assignee": 5,
        }

        result = parser._extract_row(row, col_indices)

        assert result is not None
        assert result["title"] == "GPU 메모리 부족"
        assert result["created_at"] == "2024-03-15"
        assert result["assignee"] == "Sujin"

    # === _build_embedding_text 테스트 ===

    def test_build_embedding_text_구조화된_텍스트를_생성한다(self, monkeypatch):
        """임베딩 텍스트 조합 확인"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
        })())

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족",
            "created_at": "2024-03-15",
            "basic_check": "로그 확인",
            "basic_work": "메모리 최적화",
            "instruction": "긴급 처리",
            "assignee": "Sujin",
            "progress": "50%",
            "completed_at": None,
            "analysis": None,
        }

        result = parser._build_embedding_text(row)

        assert "[이슈] GPU 메모리 부족" in result
        assert "[등록일] 2024-03-15" in result
        assert "[기본 확인내용] 로그 확인" in result
        assert "[기본 작업내용] 메모리 최적화" in result
        assert "[업무지시] 긴급 처리" in result
        assert "[담당자] Sujin" in result
        assert "[진행] 50%" in result

    def test_build_embedding_text_완료일과_분석을_포함한다(self, monkeypatch):
        """완료일과 분석 내용 포함"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
        })())

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족",
            "created_at": "2024-03-15",
            "basic_check": "",
            "basic_work": "",
            "instruction": "",
            "assignee": "Sujin",
            "progress": "완료",
            "completed_at": "2024-03-20",
            "analysis": "메모리 누수 발견",
        }

        result = parser._build_embedding_text(row)

        assert "[완료일] 2024-03-20" in result
        assert "[문제 원인 분석 결과] 메모리 누수 발견" in result

    # === _build_chunks 테스트 ===

    def test_build_chunks_1row는_1chunk이다(self, monkeypatch):
        """기본: 1 row = 1 chunk"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        monkeypatch.setattr("app.services.parsers.excel_issue_parser.settings", type("Settings", (), {
            "excel_id_prefix": "issue",
            "excel_row_max_chars": 1000,
        })())

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족",
            "created_at": "2024-03-15",
            "basic_check": "로그 확인",
            "basic_work": "",
            "instruction": "",
            "assignee": "Sujin",
            "progress": "진행",
            "completed_at": None,
            "analysis": None,
        }

        chunks = parser._build_chunks(row, 1, "issue")

        assert len(chunks) == 1
        assert chunks[0]["metadata"]["split_index"] == 0
        assert "GPU 메모리 부족" in chunks[0]["embedding_text"]

    def test_build_chunks_긴_row는_분할된다(self):
        """긴 row는 분할 (요약 + 분석)"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족 오류가 발생하여 서비스가 중단되었습니다. "
                     "많은 사용자가 접속하면 GPU 메모리가 부족해지는 현상이 있습니다. "
                     "이를 해결하기 위한 방안을 찾아야 합니다.",
            "created_at": "2024-03-15",
            "basic_check": "로그 확인",
            "basic_work": "메모리 최적화",
            "instruction": "긴급 처리",
            "assignee": "Sujin",
            "progress": "진행",
            "completed_at": None,
            "analysis": "원인을 분석한 결과, 배치 사이즈가 너무 커서 메모리를 "
                       "과도하게 사용하는 것으로 확인되었습니다. 첫 번째 시도로는 "
                       "배치 사이즈를 줄여서 테스트해보았습니다. 두 번째 시도로는 "
                       "모델을 양자화하여 메모리 사용량을 줄였습니다. 세 번째 시도로는 "
                       "그라디언트 축적을 사용하여 배치를 나누어 처리했습니다. "
                       "결과적으로 세 가지 방법을 모두 적용하여 메모리 사용량을 "
                       "약 60% 줄일 수 있었습니다.",
        }

        chunks = parser._build_chunks(row, 1, "issue", max_chars=100)

        # 분할되면 최소 2개 (요약 + 분석)
        assert len(chunks) >= 2
        assert chunks[0]["metadata"]["split_index"] == 0
        assert chunks[0]["metadata"]["flow_name"] == "이슈 요약"

    def test_build_chunks_max_chars_0도_그대로_반영한다(self):
        """max_chars=0 전달 시 settings로 폴백하지 않고 분할 판단"""
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        parser = ExcelIssueParser()
        row = {
            "title": "GPU 메모리 부족",
            "created_at": "2024-03-15",
            "basic_check": "로그 확인",
            "basic_work": "메모리 최적화",
            "instruction": "긴급 처리",
            "assignee": "Sujin",
            "progress": "진행",
            "completed_at": None,
            "analysis": "원인을 분석한 결과 메모리 사용량이 과도했습니다.",
            "status": "진행",
        }

        chunks = parser._build_chunks(row, 1, "issue", max_chars=0)

        assert len(chunks) >= 2


# === P1-6: labeler 테스트 ===

class TestLabeler:
    """labeler 모듈 테스트"""

    # === label_sentence 테스트 ===

    def test_label_sentence_discovery를_감지한다(self):
        """발견 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        assert label_sentence("로그를 확인해보니") == "discovery"
        assert label_sentence("문제를 발견했습니다") == "discovery"
        assert label_sentence("원인을 분석한 결과") == "discovery"

    def test_label_sentence_attempt를_감지한다(self):
        """시도 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        assert label_sentence("배치 사이즈를 줄여서 시도했습니다") == "attempt"
        assert label_sentence("코드를 추가했습니다") == "attempt"
        assert label_sentence("설정을 변경했습니다") == "attempt"

    def test_label_sentence_failure를_감지한다(self):
        """실패 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        # "시도"가 먼저 매칭되므로 순서 고려
        assert label_sentence("해결되지 않았습니다") == "failure"
        assert label_sentence("여전히 문제가 지속됩니다") == "failure"
        assert label_sentence("재현되었습니다") == "failure"

    def test_label_sentence_fix를_감지한다(self):
        """수정 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        assert label_sentence("코드를 수정했습니다") == "fix"
        assert label_sentence("버그를 제거했습니다") == "fix"
        assert label_sentence("패치를 반영했습니다") == "fix"

    def test_label_sentence_result를_감지한다(self):
        """결과 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        assert label_sentence("정상 동작합니다") == "result"
        assert label_sentence("문제가 해결되었습니다") == "result"
        # "개선"은 "수정" 패턴보다 먼저 매칭되지 않음
        assert label_sentence("성능이 안정화되었습니다") == "result"

    def test_label_sentence_verification를_감지한다(self):
        """검증 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        # discovery가 "확인", "로그" 등을 먼저 매칭하므로
        # verification 패턴은 특정 키워드에만 매칭됨
        assert label_sentence("모니터링 중입니다") == "verification"
        assert label_sentence("시스템을 관찰했습니다") == "verification"
        # "재현 테스트"는 verification 패턴에 있지만 "재현"은 failure에도 있음
        # 따라서 순서에 따라 다름
        # 검증이 먼저 매칭되는 명확한 케이스만 테스트

    def test_label_sentence_next_action을_감지한다(self):
        """후속 조치 관련 키워드 감지"""
        from app.services.parsers.labeler import label_sentence

        # "추가"는 attempt 패턴에 매칭되므로 다른 키워드 사용
        assert label_sentence("향후 계획을 세워야 합니다") == "next_action"
        assert label_sentence("추후 작업이 예정되어 있습니다") == "next_action"

    def test_label_sentence_일반_문장은_other를_반환한다(self):
        """라벨에 해당하지 않는 문장은 other"""
        from app.services.parsers.labeler import label_sentence

        assert label_sentence("안녕하세요") == "other"
        assert label_sentence("일반적인 문장입니다") == "other"

    # === split_and_label 테스트 ===

    def test_split_and_label_빈_문자열은_빈_리스트를_반환한다(self):
        """빈 문자열 처리"""
        from app.services.parsers.labeler import split_and_label

        assert split_and_label("") == []
        assert split_and_label("   ") == []
        assert split_and_label(None) == []

    def test_split_and_label_단일_문장을_라벨링한다(self):
        """단일 문장 라벨링"""
        from app.services.parsers.labeler import split_and_label

        result = split_and_label("로그를 확인해보니 문제였습니다.")

        assert len(result) == 1
        assert result[0]["text"] == "로그를 확인해보니 문제였습니다."
        assert result[0]["label"] == "discovery"

    def test_split_and_label_여러_문장을_분리하고_라벨링한다(self):
        """여러 문장 분리 및 라벨링"""
        from app.services.parsers.labeler import split_and_label

        text = "로그를 확인해보니 문제였습니다. 시도했습니다. 실패했습니다."
        result = split_and_label(text)

        # KSS로 분리되므로 문장 수는 다를 수 있음
        assert len(result) >= 1
        # 최소한 하나의 discovery 라벨이 있어야 함
        assert any(r["label"] == "discovery" for r in result)

    # === build_flow_chunks 테스트 ===

    def test_build_flow_chunks_빈_리스트는_빈_결과를_반환한다(self):
        """빈 입력 처리"""
        from app.services.parsers.labeler import build_flow_chunks

        assert build_flow_chunks([]) == []

    def test_build_flow_chunks_단일_문장을_처리한다(self):
        """단일 문장 처리"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [{"text": "로그를 확인했습니다", "label": "discovery"}]
        result = build_flow_chunks(labeled)

        assert len(result) == 1
        assert result[0]["text"] == "로그를 확인했습니다"
        assert result[0]["labels"] == ["discovery"]
        assert result[0]["flow_name"] == "원인 발견"

    def test_build_flow_chunks_같은_라벨을_합친다(self):
        """같은 라벨 병합"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "로그를 확인했습니다", "label": "discovery"},
            {"text": "추가로 분석했습니다", "label": "discovery"},
        ]
        result = build_flow_chunks(labeled)

        assert len(result) == 1
        assert result[0]["labels"] == ["discovery"]
        assert "로그를 확인했습니다" in result[0]["text"]
        assert "추가로 분석했습니다" in result[0]["text"]

    def test_build_flow_chunks_attempt_failure를_합친다(self):
        """시도→실패 흐름 병합"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "시도했습니다", "label": "attempt"},
            {"text": "실패했습니다", "label": "failure"},
        ]
        result = build_flow_chunks(labeled)

        assert len(result) == 1
        assert result[0]["labels"] == ["attempt", "failure"]
        assert result[0]["flow_name"] == "시도 및 실패"

    def test_build_flow_chunks_fix_result를_합친다(self):
        """수정→결과 흐름 병합"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "코드를 수정했습니다", "label": "fix"},
            {"text": "정상 동작합니다", "label": "result"},
        ]
        result = build_flow_chunks(labeled)

        assert len(result) == 1
        assert result[0]["labels"] == ["fix", "result"]
        assert result[0]["flow_name"] == "수정 및 결과"

    def test_build_flow_chunks_다른_라벨은_분리한다(self):
        """자연스럽지 않은 라벨 조합 분리"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "로그를 확인했습니다", "label": "discovery"},
            {"text": "코드를 수정했습니다", "label": "fix"},
        ]
        result = build_flow_chunks(labeled)

        # discovery와 fix는 자연스러운 흐름이 아니므로 분리
        assert len(result) == 2
        assert result[0]["labels"] == ["discovery"]
        assert result[1]["labels"] == ["fix"]

    def test_build_flow_chunks_other는_독립_처리한다(self):
        """other 라벨은 독립 처리"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "로그를 확인했습니다", "label": "discovery"},
            {"text": "일반 문장입니다", "label": "other"},
            {"text": "추가로 분석했습니다", "label": "discovery"},
        ]
        result = build_flow_chunks(labeled)

        # other는 독립 청크
        assert len(result) == 3
        assert result[1]["labels"] == ["other"]

    def test_build_flow_chunks_복잡한_흐름을_처리한다(self):
        """복잡한 다단계 흐름 처리"""
        from app.services.parsers.labeler import build_flow_chunks

        labeled = [
            {"text": "로그를 확인했습니다", "label": "discovery"},
            {"text": "원인을 파악했습니다", "label": "discovery"},
            {"text": "첫 번째 시도를 했습니다", "label": "attempt"},
            {"text": "실패했습니다", "label": "failure"},
            {"text": "두 번째 시도를 했습니다", "label": "attempt"},
            {"text": "코드를 수정했습니다", "label": "fix"},
            {"text": "정상 동작합니다", "label": "result"},
        ]
        result = build_flow_chunks(labeled)

        # discovery / attempt+failure / attempt+fix+result
        assert len(result) >= 2
        # 첫 번째는 discovery
        assert result[0]["labels"] == ["discovery"]
        assert result[0]["flow_name"] == "원인 발견"
