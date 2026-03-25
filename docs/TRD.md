# TRD — Simple RAG Chat 기술 참조

**문서 버전**: 1.1  
**기준일**: 2026-03-24  
**상태**: 현재 구현 반영

## 1. 시스템 개요

Simple RAG Chat은 정형 채팅 로그를 검색 가능한 임베딩 단위로 저장한 뒤, 규칙 기반 질의 분석과 벡터 검색을 결합해 답변하는 FastAPI 애플리케이션이다.

핵심 목표:

- 채팅 로그 1줄을 1개의 검색 단위로 유지
- 날짜, 채팅방, 사용자 필터를 빠르게 적용
- 답변 생성기는 Ollama 또는 프록시/직접 호출 기반 LLM으로 교체 가능

## 2. 현재 아키텍처

```text
브라우저 UI
  -> FastAPI
    -> /documents
    -> /query
    -> /query/stream
    -> /health
    -> /health/llm
  -> query_analyzer
  -> retrieval
  -> vector_store(chroma)
  -> LLM(ollama | claude proxy | codex gateway(proxy|direct))
```

### 주요 구성 요소

- `app/api/documents.py`
  - 텍스트/파일 업로드
  - 문서 목록/상세/삭제
- `app/api/query.py`
  - 일반 응답과 SSE 스트리밍 응답
- `app/services/chunking.py`
  - 채팅 로그 파싱
  - 메시지 본문 내 쉼표 보존
  - `date_int` 메타데이터 생성
- `app/services/query_analyzer.py`
  - 날짜/기간/채팅방/사용자 추출
  - 의도 분류
  - 검색 전략 선택
- `app/services/retrieval.py`
  - `vector`, `metadata`, `hybrid`, `aggregate`
- `app/services/llm.py`
  - `OllamaLLM`
  - `ProxyLLM`
  - `CodexDirectLLM`
  - `GatewayLLM`
  - 프록시/direct 상태 확인, 재시도, 스트리밍 오류 처리
- `app/database.py`
  - ChromaDB 핸들
  - `documents.json` 메타데이터 저장

## 3. 데이터 모델

### 입력 형식

```text
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

예시:

```text
[2026-03-21, 10:14:00, 개발팀, 배포 전 최종 체크 부탁드립니다, 김민수]
```

### 청크 메타데이터

| 필드 | 타입 | 설명 |
|------|------|------|
| `document_id` | string | 문서 ID |
| `chunk_index` | int | 문서 내 순번 |
| `filename` | string | 원본 파일명 |
| `room` | string | 채팅방 |
| `user` | string | 사용자 |
| `date` | string | `YYYY-MM-DD` |
| `date_int` | int | `YYYYMMDD` |
| `time` | string | `HH:MM:SS` |
| `original` | string | 원본 라인 |

### 저장 전략

- 임베딩 텍스트: `"{room} {user}: {content}"`
- 메타데이터 필터: room/user/date/date_int/time
- 문서 메타데이터: `chroma_db/documents.json`

## 4. 질의 분석 규칙

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

상대 날짜 기준은 하드코딩하지 않고, 저장된 데이터의 최신 날짜를 우선 사용한다.

### 채팅방/사용자 처리

- 채팅방은 실제 Chroma 메타데이터의 고유 room 목록에서 동적 추출
- 사용자도 실제 user 목록 기준으로 매칭
- 이름 추측용 한국어 정규식은 사용하지 않음

### 전략 선택

| 전략 | 사용 조건 |
|------|-----------|
| `vector` | 필터 없이 내용 검색 중심 |
| `metadata` | 날짜/채팅방/사용자 필터만으로 충분할 때 |
| `hybrid` | 필터와 내용 검색이 함께 필요할 때 |
| `aggregate` | 목록/집계/통계 질의일 때 |

## 5. LLM 구성

### Ollama 모드

- 임베딩: `bge-m3`
- 답변: `qwen2.5-coder:7b`

### 프록시 모드

- provider: `claude` 또는 `codex`
- 엔드포인트: OpenAI 호환 `/v1/chat/completions`
- 인증: `Authorization: Bearer <PROXY_API_KEY>`
- 상태 확인: `/v1/models`

### Codex 게이트웨이 모드

- provider: `codex`
- transport:
  - `proxy`: 기존 OpenAI 호환 프록시 경로
  - `direct`: `chatgpt.com/backend-api/codex/responses`
- 라우팅 모드:
  - `stable`
  - `fastest`
  - `proxy_only`
  - `direct_only`
- direct 인증:
  - 기본 `~/.codex/auth.json`
  - fallback `~/.chatgpt-codex-proxy/tokens.json`
  - access token 만료 임박 시 refresh token으로 갱신

### 프록시 안정성 처리

- 동시 요청 직렬화
- 일시적 오류 재시도
  - `429`, `500`, `502`, `503`, `504`
  - `auth_unavailable`
  - timeout 계열
- 스트리밍 응답의 에러 본문 파싱

## 6. API 요약

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

## 7. 환경 변수

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
| `LLM_SELFTEST_ON_STARTUP` | `false` | startup self-test/warmup 수행 |
| `VECTOR_DB_TYPE` | `chroma` | 벡터 저장소 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Chroma 저장 경로 |
| `TOP_K` | `5` | 기본 검색 결과 수 |

## 8. 테스트 범위

현재 테스트 파일:

- `tests/test_chunking.py`
- `tests/test_query_analyzer.py`
- `tests/test_documents.py`
- `tests/test_llm_proxy.py`
- `tests/test_llm_gateway.py`

검증하는 항목:

- 쉼표 포함 메시지 파싱
- `date_int` 메타데이터 생성
- 사용자 이름 오탐 방지
- 상대 날짜 계산
- 문서 삭제 API 계약
- 프록시 인증 헤더/재시도/직렬화/에러 처리
- Codex auth 파싱/refresh 경로
- gateway fallback과 `fastest` 라우팅

## 9. 운영 메모

- UI는 `/health/llm` 결과로 실제 provider 상태를 표시한다.
- 프록시 모드여도 임베딩은 Ollama에 의존한다.
- `fastest` 모드는 warmup 샘플이 없으면 초기에 `stable` 순서로 동작할 수 있다.
- 포트 `8000` 충돌 시 `8001`로 실행해도 무방하다.
