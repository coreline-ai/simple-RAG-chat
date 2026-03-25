"""파서 팩토리 — 파일명 기반 자동 파서 선택"""
from __future__ import annotations

from typing import Any

from app.services.parsers.base import BaseParser


class ParserFactory:
    """파일 확장자 기반으로 적절한 파서를 생성"""

    @staticmethod
    def create(filename: str) -> BaseParser:
        """파일명에 맞는 파서 인스턴스 반환"""
        from app.services.parsers.chat_log_parser import ChatLogParser
        from app.services.parsers.excel_issue_parser import ExcelIssueParser

        parsers: list[BaseParser] = [ChatLogParser(), ExcelIssueParser()]

        for parser in parsers:
            if parser.detect(filename):
                return parser

        raise ValueError(f"지원하지 않는 파일 형식: {filename}")

    @staticmethod
    def parse_file(filename: str, source: Any) -> list[dict]:
        """파일명으로 파서 선택 후 바로 파싱 실행"""
        parser = ParserFactory.create(filename)
        return parser.parse(source)
