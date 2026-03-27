"""성능 벤치마크 테스트 - 대용량 데이터 처리 성능 검증

주의: 이 테스트는 실행에 시간이 오래 걸릴 수 있습니다.
pytest -v tests/test_performance.py --tb=short 로 실행하세요.
"""
from __future__ import annotations

import gc
import time

import pytest


# === 성능 테스트 마크 ===

# 성능 테스트는 기본적으로 skip됨
# 실행하려면: pytest tests/test_performance.py -v --run-performance

performance = pytest.mark.performance


# === 테스트 데이터 생성 유틸리티 ===

def _generate_large_chat_log(num_lines: int) -> str:
    """대량 채팅 로그 생성"""
    rooms = ["개발팀", "마케팅팀", "기획팀", "디자인팀", "운영팀"]
    users = ["김민수", "박서준", "이지영", "최현우", "서연"]
    contents = [
        "작업이 완료되었습니다",
        "회의를 진행했습니다",
        "보고서를 작성했습니다",
        "코드를 리뷰했습니다",
        "배포를 완료했습니다",
    ]

    lines = []
    for i in range(num_lines):
        room = rooms[i % len(rooms)]
        user = users[i % len(users)]
        content = contents[i % len(contents)]

        day = 1 + (i // 100) % 28
        month = 3
        hour = 9 + (i // 10) % 12
        minute = i % 60

        date_str = f"2024-0{month:02d}-0{day:02d}"
        time_str = f"{hour:02d}:{minute:02d}:00"

        line = f"[{date_str}, {time_str}, {room}, {content}, {user}]"
        lines.append(line)

    return "\n".join(lines)


# === P2-3: 성능 벤치마크 테스트 ===

@performance
def test_파싱_성능_1000건_처리_시간_측정():
    """채팅 로그 1000건 파싱 성능 측정"""
    from app.services.parsers.chat_log_parser import ChatLogParser

    parser = ChatLogParser()
    large_log = _generate_large_chat_log(1000)

    start_time = time.time()
    results = parser.parse(large_log)
    elapsed = time.time() - start_time

    print(f"\n1000건 파싱 시간: {elapsed:.2f}초")
    print(f"초당 처리 건수: {len(results) / elapsed:.1f}건/초")

    assert elapsed < 10.0, "1000건 파싱이 10초를 초과함"
    assert len(results) == 1000


@performance
def test_파싱_성능_10000건_처리_시간_측정():
    """채팅 로그 10000건 파싱 성능 측정"""
    from app.services.parsers.chat_log_parser import ChatLogParser

    parser = ChatLogParser()
    large_log = _generate_large_chat_log(10000)

    start_time = time.time()
    results = parser.parse(large_log)
    elapsed = time.time() - start_time

    print(f"\n10000건 파싱 시간: {elapsed:.2f}초")
    print(f"초당 처리 건수: {len(results) / elapsed:.1f}건/초")

    assert elapsed < 60.0, "10000건 파싱이 60초를 초과함"
    assert len(results) == 10000


@performance
def test_메모리_사용량_대량_파싱_시_측정():
    """대량 파싱 시 메모리 사용량 측정"""
    from app.services.parsers.chat_log_parser import ChatLogParser

    # 메모리 추적 시작
    import tracemalloc
    tracemalloc.start()
    gc.collect()

    parser = ChatLogParser()
    large_log = _generate_large_chat_log(5000)

    # 파싱 전 메모리
    gc.collect()
    current1, _ = tracemalloc.get_traced_memory()

    # 파싱 실행
    results = parser.parse(large_log)
    gc.collect()
    current2, _ = tracemalloc.get_traced_memory()

    tracemalloc.stop()

    memory_used = (current2 - current1) / 1024 / 1024  # MB
    print(f"\n5000건 파싱 시 메모리 사용: {memory_used:.2f}MB")
    print(f"건당 메모리: {memory_used / len(results) * 1024:.2f}KB/건")

    assert memory_used < 100, f"메모리 사용량이 100MB를 초과함: {memory_used:.2f}MB"


@performance
def test_파싱_성능_session_vs_line_전략_비교():
    """session 전략과 line 전략의 성능 비교"""
    from app.services.parsers.chat_log_parser import ChatLogParser
    from app.config import settings

    parser = ChatLogParser()
    large_log = _generate_large_chat_log(1000)

    # line 전략
    original_strategy = settings.chunking_strategy
    settings.chunking_strategy = "line"

    start_time = time.time()
    results_line = parser.parse(large_log)
    time_line = time.time() - start_time

    # session 전략
    settings.chunking_strategy = "session"
    start_time = time.time()
    results_session = parser.parse(large_log)
    time_session = time.time() - start_time

    # 원복
    settings.chunking_strategy = original_strategy

    print(f"\nline 전략: {len(results_line)}청크, {time_line:.2f}초")
    print(f"session 전략: {len(results_session)}청크, {time_session:.2f}초")
    print(f"session 청크 감소율: {(1 - len(results_session) / len(results_line)) * 100:.1f}%")

    assert len(results_session) < len(results_line)


@performance
def test_캐시_성능_대량_데이터_저장_조회(tmp_path):
    """캐시 대량 데이터 저장/조회 성능"""
    from app.services.embedding_cache import EmbeddingCache

    cache = EmbeddingCache(db_path=tmp_path / "perf_cache.db")

    # 1000건 저장 성능
    start_time = time.time()
    for i in range(1000):
        cache.put(f"key{i}", [0.1, 0.2, 0.3, 0.4])
    put_time = time.time() - start_time

    # 1000건 조회 성능
    start_time = time.time()
    for i in range(1000):
        cache.get(f"key{i}")
    get_time = time.time() - start_time

    print(f"\n1000건 저장 시간: {put_time:.2f}초")
    print(f"1000건 조회 시간: {get_time:.2f}초")

    assert put_time < 1.0, f"저장 성능 미달: {put_time:.2f}초"
    assert get_time < 0.5, f"조회 성능 미달: {get_time:.2f}초"


@performance
def test_캐시_히트율_측정(tmp_path):
    """캐시 히트율 측정"""
    from app.services.embedding_cache import EmbeddingCache

    cache = EmbeddingCache(db_path=tmp_path / "hitrate_cache.db")

    # 100건 저장
    for i in range(100):
        cache.put(f"key{i}", [0.1, 0.2, 0.3, 0.4])

    # 50건 조회 (히트)
    for i in range(50):
        cache.get(f"key{i}")

    # 50건 조회 (미스)
    for i in range(100, 150):
        cache.get(f"key{i}")

    stats = cache.stats
    print(f"\n캐시 통계: 히트={stats['hits']}, 미스={stats['misses']}, 히트율={stats['hit_rate']}")

    # 히트율 검증
    assert stats['hits'] >= 50  # 최소 50건 히트해야 함


@performance
def test_파서_detect_성능_대량_호출():
    """파서 detect() 메서드 성능 테스트"""
    from app.services.parsers.chat_log_parser import ChatLogParser

    parser = ChatLogParser()

    filenames = [
        "test.txt", "document.txt", "data.xlsx", "data.xls",
        "script.py", "image.png", "", "no_extension"
    ]

    start_time = time.time()
    for _ in range(1000):
        for filename in filenames:
            parser.detect(filename)
    elapsed = time.time() - start_time

    print(f"\n8000회 detect() 호출 시간: {elapsed:.3f}초")

    assert elapsed < 1.0, "detect() 성능이 기준 미달"
