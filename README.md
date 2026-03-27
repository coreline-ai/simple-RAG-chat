<div align="center">

# Simple RAG Chat

**정형 채팅 로그와 엑셀 이슈 데이터를 위한 로컬 우선 RAG 시스템**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ollama](https://img.shields.io/badge/Ollama-Embeddings-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.6-FF6F00?style=for-the-badge)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

Ollama 기반 임베딩과 ChromaDB를 사용해 정형 데이터를 검색하고, Ollama 또는 프록시 LLM으로 답변을 생성합니다.
기본 모드는 로컬 실행이며, 필요 시 Claude/Codex 프록시 또는 Codex 게이트웨이 라우팅을 붙일 수 있습니다.

[빠른 시작](#-빠른-시작) · [아키텍처](#-아키텍처) · [데이터 형식](#-지원-데이터-형식) · [API](#-api)

</div>

---

## ✨ 주요 특징

| 특징 | 설명 |
|------|------|
| 로컬 우선 실행 | `LLM_PROVIDER=ollama`면 API 키 없이 동작하고, 필요 시 `claude`/`codex` 프록시로 전환 가능 |
| 규칙 기반 쿼리 분석 | 날짜, 채팅방, 사용자, 담당자, 상태를 규칙 기반으로 추출하고 검색 전략을 자동 선택 |
| 4가지 검색 전략 | `vector`, `metadata`, `hybrid`, `aggregate` 라우팅 지원 |
| 멀티 데이터 소스 | `.txt` 채팅 로그와 `.xlsx/.xls` 이슈 데이터를 `ParserFactory`로 자동 분기 |
| 가변 청킹 전략 | 채팅 로그는 `line` / `session` / `kss`, 엑셀은 row chunking + flow chunking 지원 |
| 임베딩 안정성 | Ollama 임베딩은 SQLite 캐시, bounded retry(최대 3회), 동시성 제한을 사용 |
| 안전한 캐시 폴백 | 임베딩 캐시 초기화 실패 시 no-op 캐시로 폴백해 서비스 경로를 유지 |
| 검색 캐시 | 질의 결과를 TTL 캐시로 재사용하고 크기를 256개로 제한 |
| 유연한 LLM 계층 | Ollama / Claude proxy / Codex gateway(`proxy`, `direct`, `fastest`) 지원 |
| SSE 스트리밍 | `/query/stream`으로 토큰 단위 스트리밍 응답 제공 |
| 운영 관찰성 | `/health`, `/health/llm`, 요청 지연시간 로깅 지원 |

---

## 🚀 빠른 시작

### 사전 요구사항

- Python 3.11+
- Ollama
- 선택 사항: Claude/Codex용 OpenAI 호환 프록시 또는 Codex direct 인증 정보

> 임베딩은 항상 Ollama를 사용하므로, 프록시 모드여도 `bge-m3`는 필요합니다.

### 1. 모델 설치

```bash
ollama pull bge-m3
ollama pull qwen2.5-coder:7b
```

### 2. 프로젝트 설정

```bash
git clone https://github.com/coreline-ai/simple-RAG-chat.git
cd simple-RAG-chat
python3 -m pip install -r requirements.txt
cp .env.example .env
```

### 3. 데이터 업로드

```bash
python3 generate_data.py
python3 upload_data.py
```

직접 API로 업로드할 수도 있습니다.

- `POST /documents`: 텍스트 업로드
- `POST /documents/upload-file`: `.txt`, `.xlsx`, `.xls` 파일 업로드

### 4. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. 접속

| 주소 | 설명 |
|------|------|
| http://localhost:8000 | 채팅 UI |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/health | 서버 상태 |
| http://localhost:8000/health/llm | LLM 상태 및 transport 메트릭 |

---

## 🏗 아키텍처

```text
브라우저 UI
  -> FastAPI
    -> /documents
    -> /query
    -> /query/stream
    -> /health
    -> /health/llm
  -> ParserFactory
    -> ChatLogParser(.txt)
    -> ExcelIssueParser(.xlsx/.xls)
  -> Embedding
    -> SQLite cache / NoOp fallback
    -> Ollama /api/embed
  -> QueryAnalyzer
  -> Retrieval
    -> vector / metadata / hybrid / aggregate
    -> TTL query cache
  -> LLM
    -> Ollama
    -> ProxyLLM(claude/codex)
    -> GatewayLLM(proxy/direct/fastest)
  -> ChromaDB + documents.json
```

### 업로드 파이프라인

1. `ParserFactory`가 파일 확장자로 파서를 선택합니다.
2. 파서가 구조화된 `embedding_text`, `original`, `metadata` 청크를 생성합니다.
3. 임베딩은 50개 배치 단위로 처리되고, Ollama 요청은 bounded retry와 세마포어를 사용합니다.
4. Chroma 저장이 끝난 뒤에만 `documents.json` 메타데이터를 등록합니다.
5. 문서 변경 시 질의 분석 캐시와 검색 캐시를 함께 무효화합니다.

### 질의 파이프라인

1. 규칙 기반 분석기가 날짜, 상대 기간, 방, 사용자, 담당자, 상태, 의도를 추출합니다.
2. 분석 결과에 따라 `vector` / `metadata` / `hybrid` / `aggregate` 전략을 선택합니다.
3. 검색 결과를 컨텍스트로 조합하고 의도별 힌트를 추가합니다.
4. `/query`는 JSON, `/query/stream`은 SSE로 응답합니다.

---

## 📊 지원 데이터 형식

### 1. 채팅 로그 (`.txt`)

입력 형식:

```text
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

예시:

```text
[2024-02-21, 14:30:00, 백엔드개발, 서버 배포 3차 완료했습니다, 김민수]
```

지원 청킹:

- `line`: 1줄 = 1청크
- `session`: 시간 간격과 최대 줄 수 기준 세션 묶기
- `kss`: 긴 메시지를 문장 단위로 분리

주요 메타데이터:

- `doc_type=chat`
- `room`, `user`
- `date`, `date_int`
- `time`, `time_end`, `message_count`
- `split_index`

### 2. 엑셀 이슈 데이터 (`.xlsx`, `.xls`)

대표 컬럼:

- `모델 이슈 검토 사항`
- `등록일`
- `기본 확인내용`
- `기본 작업내용`
- `업무지시`
- `담당자`
- `진행(담당자)`
- `완료일`
- `문제점 분석 내용 (담당자 Comments)`

청킹 규칙:

- 기본: 1 row = 1 사건 = 1 chunk
- 길이 초과 시: 이슈 요약 + 분석 flow chunk로 분리
- 분석 텍스트는 KSS + 라벨링으로 행동 흐름 단위로 재구성

주요 메타데이터:

- `doc_type=issue`
- `doc_id`, `title`, `assignee`, `status`
- `created_at_iso`, `created_at_int`
- `start_at_int`, `due_at_int`, `completed_at_int`
- 하위 호환용 `date`, `date_int`

---

## 🔎 지원 질의 유형

| 유형 | 예시 | 기본 전략 |
|------|------|----------|
| 내용 검색 | `서버 배포 관련 대화 찾아줘` | `vector` |
| 날짜 검색 | `2025-03-01 일어난 일 요약해줘` | `hybrid` |
| 날짜 범위 | `3월 이슈 보여줘` | `hybrid` |
| 담당자 검색 | `Sujin 담당 이슈는?` | `metadata` |
| 채팅방 검색 | `AI연구팀 대화 알려줘` | `metadata` |
| 집계/통계 | `가장 많은 이슈를 처리한 담당자는?` | `aggregate` |
| 복합 필터 | `3월에 Sujin이 완료한 이슈` | `hybrid` |

상대 날짜는 시스템 시간이 아니라 저장된 데이터의 최신 날짜를 우선 기준으로 계산합니다.

---

## ⚙️ LLM 모드 설정

### Ollama 모드

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
EMBEDDING_MODEL=bge-m3
```

### Claude 프록시 모드

```env
LLM_PROVIDER=claude
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CLAUDE_MODEL=claude-sonnet-latest
```

### Codex 게이트웨이 모드

```env
LLM_PROVIDER=codex
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CODEX_MODEL=gpt-5-codex
LLM_ROUTING_MODE=stable
```

Codex 라우팅 모드:

| 모드 | 설명 |
|------|------|
| `stable` | `proxy` 우선, 실패 시 `direct` fallback |
| `fastest` | 최근 latency 기준으로 transport 선택 |
| `proxy_only` | 프록시만 사용 |
| `direct_only` | direct만 사용 |

`LLM_WARMUP_ON_STARTUP=true` 또는 `LLM_SELFTEST_ON_STARTUP=true`를 사용하면 게이트웨이 warmup을 수행합니다.

---

## 📁 프로젝트 구조

```text
simple-rag-chat/
├── app/
│   ├── api/
│   │   ├── documents.py
│   │   └── query.py
│   ├── services/
│   │   ├── chunking.py
│   │   ├── embedding.py
│   │   ├── embedding_cache.py
│   │   ├── llm.py
│   │   ├── query_analyzer.py
│   │   ├── retrieval.py
│   │   ├── parsers/
│   │   └── vector_stores/
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── schemas.py
│   └── static/index.html
├── docs/
│   ├── PRD.md
│   └── TRD.md
├── tests/
├── generate_data.py
├── upload_data.py
├── pytest.ini
└── requirements.txt
```

---

## 📡 API

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/documents` | 텍스트 업로드 |
| `POST` | `/documents/upload-file` | 파일 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `GET` | `/documents/{id}` | 문서 상세 |
| `DELETE` | `/documents/{id}` | 문서 삭제 |
| `POST` | `/query` | JSON 질의 응답 |
| `POST` | `/query/stream` | SSE 스트리밍 질의 응답 |
| `GET` | `/health` | 서버 상태 |
| `GET` | `/health/llm` | provider, model, routing, selected transport, metrics |

---

## 🧪 테스트

```bash
pytest -q
```

기본 테스트 범위:

- 청킹 및 파서
- 문서 업로드/삭제 API
- 질의 분석기
- 검색 전략 및 캐시
- 임베딩 재시도/오류 처리
- LLM proxy / gateway
- E2E

성능 테스트는 기본 skip이며 `--run-performance`로 실행합니다.

```bash
pytest -q --run-performance
```

`pytest.ini`에는 asyncio loop scope, `performance` marker, 알려진 외부 경고 필터가 반영되어 있습니다.

---

## 🔧 주요 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Ollama 답변 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama 임베딩 모델 |
| `LLM_PROVIDER` | `ollama` | `ollama` / `claude` / `codex` |
| `PROXY_API_URL` | `http://localhost:8080` | OpenAI 호환 프록시 주소 |
| `PROXY_API_KEY` | 빈 값 | 프록시 Bearer 토큰 |
| `CLAUDE_MODEL` | `claude-sonnet-latest` | Claude 프록시 모델명 |
| `CODEX_MODEL` | `gpt-5-codex` | Codex 모델명 |
| `LLM_ROUTING_MODE` | `stable` | `stable` / `fastest` / `proxy_only` / `direct_only` |
| `CODEX_PROXY_ENABLED` | `true` | Codex 프록시 transport 활성화 |
| `CODEX_DIRECT_ENABLED` | `true` | Codex direct transport 활성화 |
| `CODEX_DIRECT_BASE_URL` | `https://chatgpt.com/backend-api` | Codex direct backend 주소 |
| `CODEX_AUTH_PATH` | `~/.codex/auth.json` | Codex auth 파일 경로 |
| `CODEX_FALLBACK_AUTH_PATH` | `~/.chatgpt-codex-proxy/tokens.json` | fallback auth 파일 경로 |
| `LLM_WARMUP_ON_STARTUP` | `false` | startup warmup 수행 |
| `LLM_SELFTEST_ON_STARTUP` | `false` | startup self-test 수행 |
| `VECTOR_DB_TYPE` | `chroma` | 벡터 저장소 타입 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Chroma 및 캐시 저장 경로 |
| `CHUNKING_STRATEGY` | `line` | `line` / `session` / `kss` |
| `SESSION_GAP_MINUTES` | `30` | 세션 청킹 간격 |
| `SESSION_MAX_LINES` | `10` | 세션 청킹 최대 줄 수 |
| `KSS_MIN_LENGTH` | `80` | KSS 분할 최소 길이 |
| `EXCEL_ROW_MAX_CHARS` | `600` | 엑셀 row 재분할 임계값 |
| `EXCEL_SHEET_NAME` | 빈 값 | 지정 시 해당 시트 사용 |
| `EXCEL_ID_PREFIX` | `issue` | 엑셀 문서 ID prefix |
| `USE_KIWI_KEYWORDS` | `true` | Kiwi 형태소 분석 사용 |
| `EMBEDDING_CACHE_ENABLED` | `true` | SQLite 임베딩 캐시 사용 여부 |
| `EMBEDDING_MAX_CONCURRENCY` | `3` | Ollama 동시 임베딩 요청 제한 |
| `TOP_K` | `5` | 기본 검색 결과 수 |
| `QUERY_CACHE_TTL_SECONDS` | `300` | 질의 결과 캐시 TTL |
| `SEARCH_VECTOR_MULTIPLIER` | `3` | vector 검색 시 탐색 배수 |
| `SEARCH_HYBRID_MULTIPLIER` | `4` | hybrid 검색 시 탐색 배수 |
| `SEARCH_METADATA_MULTIPLIER` | `5` | metadata 검색 시 조회 배수 |

---

## 🐛 트러블슈팅

### 프록시 모드인데 임베딩이 실패하는 경우

프록시는 답변 생성 전용입니다. 임베딩은 항상 Ollama `bge-m3`를 사용합니다.

### `fastest` 모드가 초반에 기대와 다르게 선택되는 경우

warmup 데이터가 없으면 초반 선택은 `stable`과 유사하게 동작할 수 있습니다.
`LLM_WARMUP_ON_STARTUP=true`를 권장합니다.

### `chroma_db`가 읽기 전용이거나 생성되지 않는 경우

임베딩 캐시는 no-op 캐시로 폴백하지만, Chroma와 `documents.json`을 위한 쓰기 권한은 필요합니다.

### 포트 충돌

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001
```

---

## 📚 문서

| 문서 | 설명 |
|------|------|
| [PRD](docs/PRD.md) | 제품 요구사항 정의서 |
| [TRD](docs/TRD.md) | 기술 참조 문서 |
| [CLAUDE.md](CLAUDE.md) | 프로젝트 작업 원칙 |

