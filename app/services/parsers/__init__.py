"""데이터 파서 패키지

파일 형식별 파서를 제공한다.
- ChatLogParser: 채팅 로그 (.txt)
- ExcelIssueParser: 이슈 데이터 (.xlsx)
- ParserFactory: 파일명 기반 자동 파서 선택
"""
from app.services.parsers.base import BaseParser
from app.services.parsers.factory import ParserFactory

__all__ = ["BaseParser", "ParserFactory"]
