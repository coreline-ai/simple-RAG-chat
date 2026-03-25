"""쿼리 분석기 단위 테스트"""
from datetime import date

import pytest

from app.services import query_analyzer as qa


def _stub_common(monkeypatch):
    monkeypatch.setattr(qa, "_get_known_rooms", lambda: ["개발팀", "QA팀"])
    monkeypatch.setattr(qa, "_get_known_users", lambda: ["조하윤", "안지우", "김성호"])
    monkeypatch.setattr(qa, "_get_known_assignees", lambda: ["Hyunwoo", "Seoyeon", "Taehun"])


@pytest.mark.asyncio
async def test_실제_사용자명만_매칭한다(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(qa, "_get_reference_today", lambda: date(2026, 3, 24))

    analysis = await qa.analyze_query("조하윤 메시지 기록 보여줘")

    assert analysis.user == "조하윤"
    # kiwipiepy가 조사를 제거하므로 핵심 키워드 포함 여부로 확인
    assert "메시지" in analysis.search_text or "기록" in analysis.search_text


@pytest.mark.asyncio
async def test_일반_단어는_사용자명으로_오탐하지_않는다(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(qa, "_get_reference_today", lambda: date(2026, 3, 24))

    analysis = await qa.analyze_query("보안 관련 이슈가 있었나요?")

    assert analysis.user is None
    assert "보안" in analysis.search_text
    assert "이슈" in analysis.search_text


@pytest.mark.asyncio
async def test_최근에는_상대날짜로_처리하고_이름_오탐을_막는다(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(qa, "_get_reference_today", lambda: date(2026, 3, 24))

    analysis = await qa.analyze_query("최근에 제기한 문제점을 알려줘")

    assert analysis.user is None
    assert analysis.date_from == "2026-03-17"
    assert analysis.date_to == "2026-03-24"
    assert "문제" in analysis.search_text


@pytest.mark.asyncio
async def test_연도없는_월은_데이터_기준연도를_사용한다(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(qa, "_get_reference_today", lambda: date(2025, 7, 19))

    analysis = await qa.analyze_query("3월 내용 보여줘")

    assert analysis.date_from == "2025-03-01"
    assert analysis.date_to == "2025-03-31"


@pytest.mark.asyncio
async def test_팀_전체_질문은_목록_집계로_처리한다(monkeypatch):
    _stub_common(monkeypatch)
    monkeypatch.setattr(qa, "_get_reference_today", lambda: date(2026, 3, 24))

    analysis = await qa.analyze_query("현재 팀 모두 알려줘")

    assert analysis.intent == "list"
    assert analysis.strategy == "aggregate"
