# TRD — Simple RAG Chat 기술 참조

**문서 버전**: 1.2  
**기준일**: 2026-03-27  
**상태**: 현재 구현 반영

## 1. 시스템 개요

Simple RAG Chat은 정형 채팅 로그와 엑셀 이슈 데이터를 검색 가능한 임베딩 단위로 저장한 뒤, 규칙 기반 질의 분석과 벡터 검색을 결합해 답변하는 FastAPI 애플리케이션이다.

핵심 목표:

- 정형 데이터의 메타데이터를 보존하면서 검색 가능하게 만들기
- 날짜, 채팅방, 사용자, 담당자, 상태 필터를 빠르게 적용하기
- Ollama-only와 프록시/gateway LLM 구성을 같은 API로 다루기

## 2. 현재 아키텍처

```text
브라우저 UI
  -> FastAPI
    -> /documents
    -> /query
    -> /query/stream
    -> /health
    -> /health/llm
  -> ParserFactory
    -> ChatLogParser
    -> ExcelIssueParser
  -> embedding
    -> SQLite cache / NoOp fallback
    -> Ollama /api/embed
  -> query_analyzer
  -> retrieval
    -> vector / metadata / hybrid / aggregate
    -> TTL query cache
  -> LLM(ollama | claude proxy | codex gateway(proxy|direct))
  -> vector_store(chroma)
  -> documents.json
```

### 주요 구성 요소

- `app/api/documents.py`
  - 텍스트 업로드
  - 파일 업로드
  - 문서 목록/상세/삭제
  - 업로드 원자성 유지
- `app/api/query.py`
  - 일반 JSON 응답
  - SSE 스트리밍 응답
- `app/services/parsers/chat_log_parser.py`
  - `line`, `session`, `kss` 청킹
  - 세션 기준 파라미터 오버라이드 지원
- `app/services/parsers/excel_issue_parser.py`
  - row chunking
  - 분석 flow chunking
- `app/services/embedding.py`
  - Ollama 임베딩 호출
  - bounded retry(최대 3회)
  - 세마포어 기반 동시성 제한
- `app/services/embedding_cache.py`
  - SQLite 캐시
  - 초기화 실패 시 no-op 캐시 폴백
- `app/services/query_analyzer.py`
  - 날짜/기간/방/사용자/담당자/상태 추출
  - 의도 분류
  - 검색 전략 선택
- `app/services/retrieval.py`
  - `vector`, `metadata`, `hybrid`, `aggregate`
  - TTL 기반 질의 결과 캐시
- `app/services/llm.py`
  - `OllamaLLM`
  - `ProxyLLM`
  - `CodexDirectLLM`
  - `GatewayLLM`
  - warmup, self-test, transport metrics
- `app/main.py`
  - FastAPI lifespan
  - 요청 지연시간 로깅

## 3. 데이터 모델

### 3.1 채팅 로그 입력 형식

```text
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

예시:

```text
[2026-03-21, 10:14:00, 개발팀, 배포 전 최종 체크 부탁드립니다, 김민수]
```

### 3.2 채팅 로그 메타데이터

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_id` | string | 문서 ID |
| `chunk_index` | int | 문서 내 순번 |
| `filename` | string | 원본 파일명 |
| `doc_type` | string | `chat` |
| `room` | string | 채팅방 |
| `user` | string | 사용자 또는 세션 사용자 목록 |
| `date` | string | `YYYY-MM-DD` |
| `date_int` | int | `YYYYMMDD` |
| `time` | string | `HH:MM:SS` |
| `time_end` | string | 세션 청킹 시 종료 시간 |
| `message_count` | int | 세션 청킹 시 메시지 수 |
| `split_index` | int | KSS 분할 순번 |
| `original` | string | 원본 라인 또는 세션 원문 |

### 3.3 엑셀 이슈 메타데이터

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_id` | string | 문서 ID |
| `chunk_index` | int | 문서 내 순번 |
| `filename` | string | 원본 파일명 |
| `doc_type` | string | `issue` |
| `doc_id` | string | 이슈 row 기반 ID |
| `title` | string | 이슈 제목 |
| `assignee` | string | 담당자 |
| `status` | string | 상태 |
| `created_at_iso` | string | 등록일 ISO |
| `created_at_int` | int | 등록일 정수형 |
| `start_at_int` | int | 업무시작일 정수형 |
| `due_at_int` | int | 완료예정일 정수형 |
| `completed_at_int` | int | 완료일 정수형 |
| `date` | string | 하위 호환용 등록일 |
| `date_int` | int | 하위 호환용 등록일 |
| `split_index` | int | 분할 순번 |
| `flow_name` | string | flow chunk 이름 |
| `labels` | string | flow chunk 라벨 목록 |

## 4. 업로드 및 저장 파이프라인

1. `ParserFactory`가 파일 확장자로 파서를 선택한다.
2. 파서는 `embedding_text`, `original`, `metadata` 리스트를 생성한다.
3. 업로드 API는 50개 단위 배치로 임베딩을 요청한다.
4. 임베딩은 Ollama `/api/embed`를 사용하며, timeout/5xx/429는 최대 3회 재시도한다.
5. Chroma에 청크 저장이 모두 끝난 뒤에만 `documents.json` 메타데이터를 기록한다.
6. 실패 시 이미 저장된 청크를 `document_id` 기준으로 정리한다.
7. 성공 시 질의 분석 캐시와 검색 캐시를 무효화한다.

## 5. 질의 분석 규칙

### 날짜 처리

- 정확한 날짜
  - `2026-03-24`
  - `2026년 3월 24일`
- 월 범위
  - `3월`
  - `2026년 3월`
- 상대 날짜
  - `오늘`
  - `어제`
  - `이번 주`
  - `최근`, `최근 2주`, `최근 3개월`

상대 날짜 기준은 시스템 현재 시간보다 저장된 데이터의 최신 날짜를 우선 사용한다.

### 엔티티 처리

- 채팅방은 실제 Chroma 메타데이터의 room 목록에서 동적 추출
- 사용자도 실제 user 목록 기준으로 매칭
- 담당자와 상태도 저장된 메타데이터 기준으로 필터링
- 추측용 이름 정규식보다 실제 저장값 매칭을 우선

### 전략 선택

| 전략 | 사용 조건 |
|------|-----------|
| `vector` | 필터 없이 내용 검색 중심 |
| `metadata` | 날짜/방/사용자/담당자/상태 필터만으로 충분할 때 |
| `hybrid` | 필터와 내용 검색이 함께 필요할 때 |
| `aggregate` | 목록/집계/통계 질의일 때 |

## 6. 검색 파이프라인

- `vector`
  - 질의 임베딩 후 Chroma 유사도 검색
  - `TOP_K * SEARCH_VECTOR_MULTIPLIER`까지 탐색
- `metadata`
  - Chroma metadata filter만 사용
  - `TOP_K * SEARCH_METADATA_MULTIPLIER`까지 조회
- `hybrid`
  - metadata filter + 벡터 검색
  - 필터 결과 0건이면 벡터 검색으로 폴백
  - `TOP_K * SEARCH_HYBRID_MULTIPLIER`까지 탐색
- `aggregate`
  - 필터 결과를 메모리에서 집계
  - 대표 샘플과 통계 요약 청크를 함께 생성

### 질의 결과 캐시

- 키: `(query, top_k)`
- 값: `(timestamp, results, analysis)`
- TTL: `QUERY_CACHE_TTL_SECONDS`
- 최대 크기: 256
- 문서 변경 시 전체 무효화

## 7. 임베딩 및 캐시 설계

### 임베딩 호출

- 엔드포인트: `POST {OLLAMA_BASE_URL}/api/embed`
- 모델: `EMBEDDING_MODEL`
- 동시 요청 제한: `EMBEDDING_MAX_CONCURRENCY`
- retry 대상:
  - timeout
  - `429`, `500`, `502`, `503`, `504`

### 임베딩 캐시

- 저장 위치: `{CHROMA_PERSIST_DIR}/embedding_cache.db`
- 키: `sha256("{embedding_model}:{text}")`
- 백엔드: SQLite WAL
- 초기화 실패 시 `_NoOpCache` 사용

## 8. LLM 구성

### Ollama 모드

- provider: `ollama`
- 답변 모델: `LLM_MODEL`

### 프록시 모드

- provider: `claude` 또는 `codex`
- 엔드포인트: OpenAI 호환 `/v1/chat/completions`
- 인증: `Authorization: Bearer <PROXY_API_KEY>`
- 상태 확인: `/v1/models`

### Codex 게이트웨이 모드

- provider: `codex`
- transport
  - `proxy`
  - `direct`
- 라우팅 모드
  - `stable`
  - `fastest`
  - `proxy_only`
  - `direct_only`
- direct 인증
  - 기본 `~/.codex/auth.json`
  - fallback `~/.chatgpt-codex-proxy/tokens.json`

### 상태 확인

`GET /health/llm`은 다음 정보를 반환한다.

- `provider`
- `configured_model`
- `routing_mode`
- `selected_transport`
- transport별 `ok`, `metrics`, `warnings`

## 9. API 요약

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/documents` | 텍스트 업로드 |
| `POST` | `/documents/upload-file` | 파일 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `GET` | `/documents/{id}` | 문서 상세 |
| `DELETE` | `/documents/{id}` | 문서와 청크 삭제 |
| `POST` | `/query` | 일반 질의 |
| `POST` | `/query/stream` | SSE 스트리밍 질의 |
| `GET` | `/health` | 서버 상태 |
| `GET` | `/health/llm` | provider/model/라우팅/transport 상태 |

## 10. 환경 변수

| 변수명 | 기본값 | 설명 |
|--------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 주소 |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Ollama 답변 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama 임베딩 모델 |
| `LLM_PROVIDER` | `ollama` | `ollama`, `claude`, `codex` |
| `PROXY_API_URL` | `http://localhost:8080` | 프록시 주소 |
| `PROXY_API_KEY` | 빈 값 | 프록시 토큰 |
| `CLAUDE_MODEL` | `claude-sonnet-latest` | Claude 모델명 |
| `CODEX_MODEL` | `gpt-5-codex` | Codex 모델명 |
| `LLM_ROUTING_MODE` | `stable` | `stable`, `fastest`, `proxy_only`, `direct_only` |
| `CODEX_PROXY_ENABLED` | `true` | Codex 프록시 transport 사용 |
| `CODEX_DIRECT_ENABLED` | `true` | Codex direct transport 사용 |
| `CODEX_DIRECT_BASE_URL` | `https://chatgpt.com/backend-api` | direct backend 주소 |
| `CODEX_AUTH_PATH` | `~/.codex/auth.json` | Codex auth 파일 |
| `CODEX_FALLBACK_AUTH_PATH` | `~/.chatgpt-codex-proxy/tokens.json` | fallback auth 파일 |
| `LLM_WARMUP_ON_STARTUP` | `false` | startup warmup 수행 |
| `LLM_SELFTEST_ON_STARTUP` | `false` | startup self-test 수행 |
| `VECTOR_DB_TYPE` | `chroma` | 벡터 저장소 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Chroma 및 캐시 저장 경로 |
| `CHUNKING_STRATEGY` | `line` | `line`, `session`, `kss` |
| `SESSION_GAP_MINUTES` | `30` | 세션 청킹 간격 |
| `SESSION_MAX_LINES` | `10` | 세션 청킹 최대 줄 수 |
| `KSS_MIN_LENGTH` | `80` | KSS 분할 최소 길이 |
| `USE_KIWI_KEYWORDS` | `true` | Kiwi 키워드 분석 사용 |
| `EMBEDDING_CACHE_ENABLED` | `true` | 임베딩 캐시 활성화 |
| `EMBEDDING_MAX_CONCURRENCY` | `3` | Ollama 동시 임베딩 요청 제한 |
| `EXCEL_ROW_MAX_CHARS` | `600` | 엑셀 row 재분할 임계값 |
| `EXCEL_SHEET_NAME` | 빈 값 | 지정 시 해당 시트 사용 |
| `EXCEL_ID_PREFIX` | `issue` | 엑셀 row ID prefix |
| `TOP_K` | `5` | 기본 검색 결과 수 |
| `QUERY_CACHE_TTL_SECONDS` | `300` | 질의 결과 캐시 TTL |
| `SEARCH_VECTOR_MULTIPLIER` | `3` | vector 탐색 배수 |
| `SEARCH_HYBRID_MULTIPLIER` | `4` | hybrid 탐색 배수 |
| `SEARCH_METADATA_MULTIPLIER` | `5` | metadata 조회 배수 |

## 11. 테스트 범위

현재 테스트 파일:

- `tests/test_chunking.py`
- `tests/test_documents.py`
- `tests/test_e2e.py`
- `tests/test_embedding.py`
- `tests/test_errors.py`
- `tests/test_llm_gateway.py`
- `tests/test_llm_proxy.py`
- `tests/test_parsers.py`
- `tests/test_performance.py`
- `tests/test_query_analyzer.py`
- `tests/test_retrieval.py`

검증 항목:

- 채팅 로그 라인/세션/KSS 파싱
- 엑셀 row/flow chunking
- 문서 업로드/삭제와 원자성 경계
- 임베딩 timeout/5xx/429 retry
- SQLite 캐시와 no-op fallback
- 질의 분석기 날짜/상대기간/엔티티 추출
- 검색 전략과 캐시 eviction
- 프록시/게이트웨이 라우팅과 auth 처리
- SSE 및 E2E 시나리오

## 12. 운영 메모

- `/health/llm` 결과는 UI 상태 표시에도 사용된다
- 프록시 모드여도 임베딩은 Ollama에 의존한다
- `fastest` 모드는 warmup 샘플이 없으면 초기에 `stable`과 유사하게 동작할 수 있다
- `app.main`은 정적 파일과 `favicon.ico`를 제외한 요청 지연시간을 로그로 기록한다
