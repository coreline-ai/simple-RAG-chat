# Simple RAG Chat

정형 채팅 로그를 대상으로 동작하는 로컬 RAG 애플리케이션입니다.  
FastAPI 서버가 문서 업로드, 검색, 스트리밍 응답을 제공하고, 검색 파이프라인은 `질의 분석 -> 전략 선택 -> Chroma 검색 -> LLM 답변` 순서로 동작합니다.

- 임베딩: Ollama `bge-m3`
- 답변 생성: Ollama 또는 OpenAI 호환 프록시(`codex`, `claude`)
- 벡터 저장소: ChromaDB
- UI: 단일 HTML/Vanilla JS 채팅 화면

## 현재 상태

- 채팅 로그 파서는 메시지 안의 쉼표를 보존합니다.
- 사용자 이름 매칭은 정규식 추측이 아니라 실제 저장된 사용자 목록 기준입니다.
- 날짜 범위 검색은 `date_int` 메타데이터를 사용합니다.
- 프록시 LLM은 Bearer 인증, 상태 확인, 재시도, 스트리밍 오류 노출을 지원합니다.
- UI 헤더는 `/health/llm` 결과를 읽어 실제 provider/model 상태를 표시합니다.

## 빠른 시작

### 1. 준비물

- Python 3.11+
- Ollama
- 선택 사항: Codex/Claude 프록시 서버

임베딩은 항상 Ollama를 사용하므로, 프록시 모드여도 `bge-m3`는 필요합니다.

```bash
ollama pull bge-m3
ollama pull qwen2.5-coder:7b
```

### 2. 설치

```bash
git clone https://github.com/coreline-ai/simple-rag-chat.git
cd simple-rag-chat
python3 -m pip install -r requirements.txt
cp .env.example .env
```

### 3. 데이터 생성 및 업로드

```bash
python3 generate_data.py
python3 upload_data.py
```

기본 입력 형식:

```text
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

예시:

```text
[2026-03-21, 10:14:00, 개발팀, 배포 전 최종 체크 부탁드립니다, 김민수]
[2026-03-21, 10:15:12, 개발팀, 네, 체크리스트 공유할게요, 박서준]
```

## 실행

### Ollama 모드

`.env`:

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
EMBEDDING_MODEL=bge-m3
```

### Codex 프록시 모드

`.env`:

```env
LLM_PROVIDER=codex
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CODEX_MODEL=gpt-5-codex
EMBEDDING_MODEL=bge-m3
```

### Claude 프록시 모드

`.env`:

```env
LLM_PROVIDER=claude
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CLAUDE_MODEL=claude-sonnet-latest
EMBEDDING_MODEL=bge-m3
```

### 서버 시작

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

`8000` 포트가 이미 사용 중이면 `8001` 같은 다른 포트를 쓰면 됩니다.

## 접속 및 상태 확인

| 주소 | 설명 |
|------|------|
| `http://localhost:8000` | 채팅 UI |
| `http://localhost:8000/docs` | Swagger |
| `http://localhost:8000/health` | 서버 상태 |
| `http://localhost:8000/health/llm` | LLM provider/model 상태 |

예시:

```bash
curl http://localhost:8000/health/llm
```

프록시 모드에서 `available_models`가 비어 있거나 `warning`이 나오면 프록시 alias 또는 upstream 설정을 먼저 확인해야 합니다.

## 아키텍처

```text
브라우저 UI
  -> FastAPI (/documents, /query, /query/stream, /health/llm)
  -> query_analyzer
  -> retrieval
  -> ChromaDB
  -> LLM (Ollama or ProxyLLM)
```

### 검색 파이프라인

1. `query_analyzer.py`가 날짜, 기간, 채팅방, 사용자, 의도를 규칙 기반으로 추출합니다.
2. `retrieval.py`가 `vector`, `metadata`, `hybrid`, `aggregate` 중 전략을 선택합니다.
3. ChromaDB에서 메타데이터 필터와 벡터 유사도 검색을 수행합니다.
4. 검색 결과를 컨텍스트로 조합해 LLM이 답변을 생성합니다.

### 질의 분석 규칙

- 정확한 날짜: `2026-03-24`, `2026년 3월 24일`
- 월 범위: `3월`, `2026년 3월`
- 상대 날짜: `오늘`, `어제`, `이번 주`, `최근`, `최근 2주`
- 채팅방 감지: 실제 저장된 room 목록에서 동적 추출
- 사용자 감지: 실제 저장된 user 목록에서 동적 추출
- 범위 필터: `date_int` 정수 필드 사용

상대 날짜의 기준일은 하드코딩하지 않고, 저장된 데이터의 최신 날짜를 우선 사용합니다.

## API

### `POST /documents`

텍스트 본문을 업로드해 문서와 청크를 생성합니다.

```json
{
  "filename": "chat_logs.txt",
  "content": "[2026-03-21, 10:14:00, 개발팀, 배포 전 최종 체크 부탁드립니다, 김민수]"
}
```

### `POST /documents/upload-file`

파일 업로드 방식입니다.

### `GET /documents`

저장된 문서 목록을 반환합니다.

### `DELETE /documents/{document_id}`

문서 메타데이터와 관련 청크를 함께 삭제합니다.

### `POST /query`

일반 JSON 응답입니다.

```json
{
  "question": "보안 관련 이슈가 있었나요?",
  "top_k": 5
}
```

### `POST /query/stream`

SSE 기반 스트리밍 응답입니다. 프론트 UI는 기본적으로 이 경로를 사용합니다.

## 프로젝트 구조

```text
simple-rag-chat/
├── app/
│   ├── api/
│   │   ├── documents.py
│   │   └── query.py
│   ├── services/
│   │   ├── chunking.py
│   │   ├── embedding.py
│   │   ├── llm.py
│   │   ├── query_analyzer.py
│   │   ├── retrieval.py
│   │   └── vector_stores/
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── schemas.py
│   └── static/index.html
├── data/
├── docs/
│   ├── PRD.md
│   └── TRD.md
├── tests/
│   ├── test_chunking.py
│   ├── test_documents.py
│   ├── test_llm_proxy.py
│   └── test_query_analyzer.py
├── generate_data.py
├── upload_data.py
└── requirements.txt
```

## 테스트

```bash
pytest -q
```

현재 단위 테스트는 다음 영역을 덮습니다.

- 채팅 로그 파싱과 `date_int` 생성
- 사용자 이름 오탐 방지 및 상대 날짜 해석
- 문서 삭제 API 동작
- 프록시 LLM 인증 헤더, 직렬화, 재시도, 스트리밍 오류 처리

## 주요 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Ollama 모드 답변 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama 임베딩 모델 |
| `LLM_PROVIDER` | `ollama` | `ollama`, `claude`, `codex` |
| `PROXY_API_URL` | `http://localhost:8080` | OpenAI 호환 프록시 주소 |
| `PROXY_API_KEY` | 빈 값 | 프록시 Bearer 토큰 |
| `CLAUDE_MODEL` | `claude-sonnet-latest` | Claude 프록시 모델명 |
| `CODEX_MODEL` | `gpt-5-codex` | Codex 프록시 모델명 |
| `VECTOR_DB_TYPE` | `chroma` | 현재 지원 벡터 저장소 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Chroma 저장 경로 |
| `TOP_K` | `5` | 기본 검색 개수 |

## 트러블슈팅

### `favicon.ico` 404

UI는 인라인 favicon을 사용합니다. 브라우저 캐시가 오래된 경우 강새로고침 후 다시 확인합니다.

### 프록시는 붙는데 답변이 실패함

- `/health/llm`의 `ok`는 연결 상태 기준입니다.
- 실제 completions 실패 시 `configured_model`이 `/v1/models`에 있는지 확인합니다.
- `unknown provider for model ...`이면 프록시 alias 또는 upstream 설정 문제입니다.

### 프록시 모드인데 임베딩이 실패함

프록시는 답변 생성에만 사용합니다. 임베딩은 여전히 Ollama `bge-m3`가 필요합니다.

## 문서

- [docs/PRD.md](docs/PRD.md)
- [docs/TRD.md](docs/TRD.md)
- [CLAUDE.md](CLAUDE.md)
