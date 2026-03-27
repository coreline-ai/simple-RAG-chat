# Simple RAG Chat

정형 채팅 로그와 엑셀 이슈 데이터를 처리하는 FastAPI 기반 RAG 프로젝트다.
문서는 구현 기준으로 유지하고, 코드보다 앞서가지 않는다.

## 작업 원칙

- 기본 응답과 주석은 한글 우선
- 추측보다 저장된 메타데이터와 테스트를 우선
- 변경 시 문서, 테스트, 캐시 무효화 경계를 함께 본다

## 현재 기술 스택

- Python 3.11+
- FastAPI
- ChromaDB
- Ollama `bge-m3` 임베딩
- LLM provider
  - `ollama`: `qwen2.5-coder:7b`
  - `claude`: OpenAI 호환 프록시
  - `codex`: 게이트웨이(`proxy` / `direct` / `fastest`)

## 핵심 구조

```text
app/
  api/
    documents.py      문서 업로드/조회/삭제
    query.py          일반 질의 + SSE 스트리밍
  services/
    chunking.py       하위 호환 래퍼
    embedding.py      Ollama 임베딩, retry, semaphore
    embedding_cache.py SQLite 캐시, no-op fallback
    query_analyzer.py 규칙 기반 질의 분석
    retrieval.py      vector / metadata / hybrid / aggregate, TTL cache
    llm.py            OllamaLLM, ProxyLLM, CodexDirectLLM, GatewayLLM
    parsers/
      chat_log_parser.py
      excel_issue_parser.py
      factory.py
    vector_stores/    ChromaDB 추상화
  config.py           Settings
  database.py         ChromaDB + documents.json
  main.py             FastAPI 앱, lifespan, latency logging
  static/index.html   단일 페이지 채팅 UI
tests/
  test_chunking.py
  test_documents.py
  test_e2e.py
  test_embedding.py
  test_errors.py
  test_llm_gateway.py
  test_llm_proxy.py
  test_parsers.py
  test_performance.py
  test_query_analyzer.py
  test_retrieval.py
```

## 데이터 규칙

### 채팅 로그

- 입력 형식: `[날짜, 시간, 채팅방이름, 입력내용, 사용자]`
- 메시지 본문 안의 쉼표 허용
- 청킹 전략: `line`, `session`, `kss`
- 기본 메타데이터: `doc_type`, `room`, `user`, `date`, `date_int`, `time`

### 엑셀 이슈

- 지원 형식: `.xlsx`, `.xls`
- 기본 전략: 1 row = 1 사건 = 1 chunk
- 길이 초과 시: 요약 chunk + 분석 flow chunk
- 기본 메타데이터: `doc_type`, `doc_id`, `title`, `assignee`, `status`, `created_at_iso`, `created_at_int`

## 검색 규칙

- 채팅방/사용자/담당자 후보는 실제 저장된 메타데이터에서 동적 추출
- 상대 날짜는 데이터 최신 날짜를 기준으로 계산
- 검색 전략은 `vector`, `metadata`, `hybrid`, `aggregate`
- 검색 결과는 TTL 캐시를 사용하고 최대 256개까지만 유지

## 런타임 메모

- 문서 업로드는 청크 저장 완료 후 `documents.json`을 기록해 원자성을 맞춘다
- 문서 추가/삭제 시 `query_analyzer`와 `retrieval` 캐시를 함께 무효화한다
- 임베딩 캐시 SQLite 초기화가 실패하면 no-op 캐시로 폴백한다
- `/health/llm`은 provider, configured model, routing mode, selected transport, transport별 metrics를 반환한다
- `main.py`는 정적 파일 요청을 제외한 HTTP 지연시간을 로그로 남긴다

## 테스트 메모

```bash
pytest -q
pytest -q --run-performance
```

- `pytest.ini`가 asyncio loop scope와 `performance` marker를 관리한다
- `tests/conftest.py`는 테스트마다 semaphore/lock을 리셋해 이벤트 루프 오염을 막는다
- `isolated_db` fixture는 임시 Chroma 경로와 관련 모듈을 통째로 분리한다

## 주요 설정값

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `LLM_PROVIDER` | `ollama` | `ollama` / `claude` / `codex` |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Ollama 모드 답변 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama 임베딩 모델 |
| `EMBEDDING_MAX_CONCURRENCY` | `3` | Ollama 동시 임베딩 요청 제한 |
| `EMBEDDING_CACHE_ENABLED` | `true` | SQLite 임베딩 캐시 활성화 |
| `TOP_K` | `5` | 기본 검색 결과 수 |
| `SEARCH_VECTOR_MULTIPLIER` | `3` | vector 검색 시 top_k 배수 |
| `SEARCH_HYBRID_MULTIPLIER` | `4` | hybrid 검색 시 top_k 배수 |
| `SEARCH_METADATA_MULTIPLIER` | `5` | metadata 검색 시 top_k 배수 |
| `QUERY_CACHE_TTL_SECONDS` | `300` | 쿼리 결과 캐시 TTL (0이면 비활성) |
| `CHUNKING_STRATEGY` | `line` | `line` / `session` / `kss` |
| `EXCEL_ROW_MAX_CHARS` | `600` | 엑셀 2차 KSS 분할 임계값 |
| `USE_KIWI_KEYWORDS` | `true` | kiwipiepy 형태소 분석 사용 |
| `LLM_ROUTING_MODE` | `stable` | Codex 라우팅: `stable` / `fastest` / `proxy_only` / `direct_only` |

## 운영 메모

- 프록시 모드여도 임베딩은 Ollama에 의존한다
- `LLM_WARMUP_ON_STARTUP=true` 또는 `LLM_SELFTEST_ON_STARTUP=true`면 startup 시 warmup/self-test를 수행한다
- Codex direct는 기본적으로 `~/.codex/auth.json`을 사용하고 필요 시 fallback auth 파일을 본다
