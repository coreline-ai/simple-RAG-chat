<div align="center">

# 🔍 Simple RAG Chat

**정형 데이터 기반 로컬 RAG 채팅 시스템**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.6-FF6F00?style=for-the-badge)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

<img width="782" height="669" alt="image" src="https://github.com/user-attachments/assets/838655a0-b864-4c31-b75d-cee8473b83cd" />

외부 API 키 없이, 로컬 LLM만으로 동작하는 RAG(Retrieval-Augmented Generation) 시스템입니다.
채팅 로그와 같은 **정형 데이터**에 최적화된 임베딩 전략과 **스마트 쿼리 라우팅**을 제공합니다.

[시작하기](#-빠른-시작) · [아키텍처](#-아키텍처) · [질의 유형](#-지원-질의-유형) · [문서](#-문서)

</div>

---

## ✨ 주요 특징

| 특징 | 설명 |
|------|------|
| 🔒 **완전 로컬 실행** | Ollama 기반, API 키 불필요, 데이터 외부 유출 없음 |
| 🧠 **스마트 쿼리 분석** | 규칙 기반 분석기가 질의 의도를 <1ms로 자동 분류 |
| 🔄 **4가지 검색 전략** | vector / metadata / hybrid / aggregate 자동 라우팅 |
| 📊 **정형 데이터 최적화** | 1줄 = 1임베딩 + 메타데이터 필터링 (고정 크기 청킹 ✗) |
| 🌙 **채팅 UI** | 다크 테마, 출처 접기/펼치기, 실시간 로딩 |
| 📝 **한글 우선** | 코드 주석, 응답, 로그 모두 한글 |

---

## 🚀 빠른 시작

### 사전 요구사항

- **Python** 3.11+
- **Ollama** ([설치 가이드](https://ollama.com/download))

### 1. 모델 설치

```bash
ollama pull bge-m3              # 임베딩 모델 (한국어 지원)
ollama pull qwen2.5-coder:7b    # LLM 모델
```

### 2. 프로젝트 설정

```bash
git clone https://github.com/coreline-ai/simple-rag-chat.git
cd simple-rag-chat
pip install -r requirements.txt
cp .env.example .env            # 필요 시 설정 수정
```

### 3. 데이터 생성 & 업로드

```bash
python generate_data.py         # 1만건 샘플 채팅 로그 생성
python upload_data.py           # 임베딩 + ChromaDB 저장 (~18분)
```

### 4. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 5. 접속

| 주소 | 설명 |
|------|------|
| http://localhost:8000 | 💬 채팅 UI |
| http://localhost:8000/docs | 📖 Swagger API 문서 |

---

## 🏗 아키텍처

```
┌──────────────────────────────────────────────────┐
│                  채팅 UI (브라우저)                 │
│               app/static/index.html               │
└────────────────────┬─────────────────────────────┘
                     │ HTTP
                     ▼
┌──────────────────────────────────────────────────┐
│              FastAPI 서버 (:8000)                  │
│                                                    │
│  ┌─────────────────────────────────────────────┐  │
│  │          서비스 레이어 (services/)            │  │
│  │                                              │  │
│  │  질의 → [쿼리 분석기] → [검색 라우터] → [LLM] │  │
│  │          (<1ms)      (4가지 전략)   (답변생성) │  │
│  └─────────────┬──────────────┬────────────────┘  │
└────────────────┼──────────────┼───────────────────┘
                 │              │
          ┌──────▼──────┐ ┌────▼─────┐
          │   Ollama    │ │  Ollama  │
          │   bge-m3    │ │  qwen2.5 │
          │  (임베딩)    │ │ (LLM)   │
          └──────┬──────┘ └──────────┘
                 │
          ┌──────▼──────┐
          │  ChromaDB   │
          │ (벡터 저장)  │
          └─────────────┘
```

### 2단계 파이프라인

```
사용자 질의
    │
    ▼
[1단계] 쿼리 분석 (규칙 기반, <1ms)
    ├─ 날짜 추출: "2024-02-21", "3월", "최근"
    ├─ 채팅방 매칭: DB에서 동적 조회
    ├─ 사용자 감지: 한국어 성+이름 패턴
    ├─ 의도 분류: search / summary / list / aggregate
    └─ 전략 결정: vector / metadata / hybrid / aggregate
    │
    ▼
[2단계] 스마트 검색 + LLM 답변 생성
    ├─ 전략에 따른 ChromaDB 검색
    ├─ 결과 채팅방별 그룹핑 + 시간순 정렬
    └─ Ollama LLM으로 답변 생성
    │
    ▼
응답 (answer + sources)
```

---

## 🔎 지원 질의 유형

| 유형 | 예시 | 검색 전략 |
|------|------|----------|
| 📄 **내용 검색** | "서버 배포 관련 대화를 찾아줘" | `vector` |
| 📅 **날짜 검색** | "2024-02-21 일어난 일을 요약해줘" | `hybrid` |
| 📅 **날짜 범위** | "2024년 3월 대화를 보여줘" | `hybrid` |
| 🏠 **채팅방 검색** | "AI연구팀에서 어떤 대화를 했나요?" | `metadata` |
| 👤 **사용자 검색** | "김민수가 뭐 했어?" | `hybrid` |
| 📋 **목록 나열** | "AI연구팀 팀원 이름을 알려줘" | `aggregate` |
| 📊 **통계/집계** | "가장 활발한 채팅방은?" | `aggregate` |
| 🔀 **복합 필터** | "3월에 개발팀에서 배포한 기록" | `hybrid` |
| ⏰ **상대 날짜** | "최근 대화", "이번 주 이슈" | `hybrid` |
| 📝 **요약** | "어제 무슨 일이 있었나?" | `hybrid` |

---

## 📁 프로젝트 구조

```
simple-rag-chat/
├── app/
│   ├── main.py                 # FastAPI 앱 진입점
│   ├── config.py               # 환경 설정 (Ollama, ChromaDB)
│   ├── database.py             # ChromaDB + JSON 저장소
│   ├── schemas.py              # Pydantic 요청/응답 스키마
│   ├── api/
│   │   ├── documents.py        # 문서 CRUD API
│   │   └── query.py            # 질의 응답 API
│   ├── services/
│   │   ├── chunking.py         # 채팅 로그 파싱 (1줄=1임베딩)
│   │   ├── embedding.py        # Ollama 임베딩 (bge-m3)
│   │   ├── query_analyzer.py   # 규칙 기반 쿼리 분석 (<1ms)
│   │   ├── retrieval.py        # 4가지 검색 전략 라우터
│   │   └── llm.py              # Ollama LLM 답변 생성
│   └── static/
│       └── index.html          # 채팅 UI (다크 테마)
├── tests/
│   └── test_chunking.py        # 단위 테스트
├── data/
│   └── chat_logs.txt           # 1만건 샘플 데이터
├── docs/
│   ├── PRD.md                  # 제품 요구사항 정의서
│   └── TRD.md                  # 기술 참조 문서
├── generate_data.py            # 샘플 데이터 생성기
├── upload_data.py              # 일괄 임베딩 업로드
└── requirements.txt            # Python 의존성
```

---

## 🛠 기술 스택

| 분류 | 기술 | 역할 |
|------|------|------|
| **프레임워크** | FastAPI 0.115 | REST API 서버 |
| **벡터 DB** | ChromaDB 0.6 | 벡터 + 메타데이터 저장 |
| **임베딩** | bge-m3 (Ollama) | 한국어 지원 다국어 임베딩 (1024d) |
| **LLM** | qwen2.5-coder:7b (Ollama) | 답변 생성 |
| **HTTP** | httpx 0.28 | 비동기 Ollama 통신 |
| **프론트엔드** | Vanilla JS | 의존성 없는 채팅 UI |

---

## 📡 API 엔드포인트

### 질의 응답

```http
POST /query
Content-Type: application/json

{
    "question": "AI연구팀 팀원 이름을 알려줘",
    "top_k": 10
}
```

```json
{
    "question": "AI연구팀 팀원 이름을 알려줘",
    "answer": "AI연구팀 팀원은 황태영, 이소율, 강도윤...",
    "sources": [
        {
            "id": "doc_line_42",
            "chunk_index": 42,
            "content": "[2024-03-05, 10:20:00, AI연구팀, ...]",
            "score": 0.85
        }
    ]
}
```

### 문서 관리

| Method | Endpoint | 설명 |
|--------|----------|------|
| `POST` | `/documents` | 텍스트 업로드 |
| `POST` | `/documents/upload-file` | 파일 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `GET` | `/documents/{id}` | 문서 상세 |
| `DELETE` | `/documents/{id}` | 문서 삭제 |
| `GET` | `/health` | 서버 상태 |

---

## 📊 데이터 형식

입력 데이터는 다음 형식의 채팅 로그입니다:

```
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

예시:
```
[2024-02-21, 14:30:00, 백엔드개발, 서버 배포 3차 완료했습니다, 김민수]
[2024-02-21, 14:31:00, 백엔드개발, 수고하셨습니다!, 박서준]
```

### 임베딩 전략

```
원본:  [2024-02-21, 14:30:00, 백엔드개발, 서버 배포 3차 완료, 김민수]
        │           │          │            │              │
        ▼           ▼          ▼            ▼              ▼
메타:  date      time       room       (임베딩 텍스트)     user
       date_int                     "백엔드개발 김민수:
                                     서버 배포 3차 완료"
```

---

## ⚙️ 설정

`.env` 파일로 설정을 변경할 수 있습니다:

```env
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5-coder:7b
EMBEDDING_MODEL=bge-m3
CHROMA_PERSIST_DIR=./chroma_db
TOP_K=5
```

---

## 🧪 테스트

```bash
pytest tests/ -v
```

---

## 📚 문서

| 문서 | 설명 |
|------|------|
| [PRD](docs/PRD.md) | 제품 요구사항 정의서 — 기능 목록, 질의 유형 매트릭스, 로드맵 |
| [TRD](docs/TRD.md) | 기술 참조 문서 — 아키텍처, 알고리즘, API 명세, 임베딩 전략 |

---

## 🗺 로드맵

| 순위 | 기능 | 난이도 | 임팩트 |
|------|------|--------|--------|
| 1 | SSE 스트리밍 | ⭐⭐ | 🔥🔥🔥 |
| 2 | 임베딩 캐시 | ⭐ | 🔥🔥 |
| 3 | LLM 팩토리 | ⭐⭐ | 🔥🔥🔥 |
| 4 | 벡터 DB 추상화 | ⭐⭐⭐ | 🔥🔥 |
| 5 | 멀티 데이터 소스 | ⭐⭐⭐ | 🔥🔥 |
| 6 | JWT 인증 | ⭐⭐ | 🔥 |

### 1. 스트리밍 응답 (SSE) — 체감 응답 시간 개선

> **현재**: LLM이 답변 전체를 생성할 때까지 15~210초 대기
> **개선**: 첫 토큰 0.5~2초 내 표시, 체감 대기 시간 95% 감소

SSE(Server-Sent Events)로 토큰이 생성될 때마다 즉시 클라이언트로 전송합니다.

```
현재: 사용자 → [120초 대기...] → 전체 답변 한번에 표시
개선: 사용자 → [0.5초] 첫 토큰 → [계속 스트리밍] → 완료
```

**변경 파일**: `llm.py` (stream: True), `query.py` (StreamingResponse), `index.html` (ReadableStream)

<details>
<summary>핵심 코드</summary>

```python
# llm.py - 스트리밍 생성
async def generate_stream(self, prompt, context):
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", f"{self.base_url}/api/generate",
            json={"model": self.model, "prompt": full_prompt, "stream": True}
        ) as response:
            async for line in response.aiter_lines():
                data = json.loads(line)
                yield data["response"]

# query.py - SSE 엔드포인트
@router.post("/query/stream")
async def query_stream(request: QueryRequest):
    chunks, analysis = await search_similar_chunks(request.question)
    context = build_context(chunks)

    async def event_generator():
        async for token in llm.generate_stream(request.question, context):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield f"data: {json.dumps({'done': True, 'sources': sources})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

```javascript
// index.html - 클라이언트 수신
const response = await fetch('/query/stream', { method: 'POST', body: ... });
const reader = response.body.getReader();
while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    messageDiv.textContent += parseToken(value);
}
```

</details>

---

### 2. 임베딩 캐시 — 중복 임베딩 방지

> **현재**: 같은 질의 반복 시 매번 Ollama에 임베딩 요청 (~100ms/건)
> **개선**: 2회차부터 <0.1ms (캐시 히트)

텍스트 해시를 키로 LRU 캐시에 임베딩 벡터를 저장합니다.

```
현재: "서버 배포" → [Ollama 호출 100ms] → 벡터
개선: "서버 배포" → [캐시 히트 <0.1ms] → 벡터 (2회차부터)
```

**변경 파일**: `embedding.py` (1개만)

<details>
<summary>핵심 코드</summary>

```python
class EmbeddingCache:
    def __init__(self, max_size=10000):
        self.cache = OrderedDict()
        self.max_size = max_size

    def get(self, text: str) -> list[float] | None:
        key = hashlib.md5(text.encode()).hexdigest()
        if key in self.cache:
            self.cache.move_to_end(key)  # LRU 갱신
            return self.cache[key]
        return None

    def put(self, text: str, embedding: list[float]):
        key = hashlib.md5(text.encode()).hexdigest()
        self.cache[key] = embedding
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)

_cache = EmbeddingCache()

async def get_embedding(text: str) -> list[float]:
    cached = _cache.get(text)
    if cached is not None:
        return cached
    embedding = await _call_ollama_embed(text)
    _cache.put(text, embedding)
    return embedding
```

</details>

---

### 3. LLM 팩토리 패턴 — OpenAI/Claude API 지원

> **현재**: OllamaLLM 하드코딩, 응답 15~210초
> **개선**: `.env` 한 줄로 LLM 교체, OpenAI 사용 시 응답 ~3초

팩토리 패턴으로 설정 값에 따라 LLM 인스턴스를 자동 생성합니다.

```
.env: LLM_PROVIDER=ollama  → Ollama 로컬 (기본값)
.env: LLM_PROVIDER=openai  → OpenAI API (GPT-4o-mini)
.env: LLM_PROVIDER=claude  → Claude API (Sonnet)
```

**변경 파일**: `llm.py`, `config.py`

<details>
<summary>핵심 코드</summary>

```python
class OpenAILLM(BaseLLM):
    async def generate(self, prompt, context):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": "채팅 로그 기반 RAG 시스템입니다."},
                {"role": "user", "content": RAG_PROMPT.format(context=context, prompt=prompt)}
            ]
        )
        return response.choices[0].message.content

class ClaudeLLM(BaseLLM):
    async def generate(self, prompt, context):
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        message = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": RAG_PROMPT.format(...)}]
        )
        return message.content[0].text

class LLMFactory:
    @staticmethod
    def create(provider: str = None) -> BaseLLM:
        provider = provider or settings.llm_provider
        match provider:
            case "ollama":  return OllamaLLM()
            case "openai":  return OpenAILLM()
            case "claude":  return ClaudeLLM()

llm = LLMFactory.create()
```

</details>

---

### 4. 벡터 DB 추상화 — Qdrant/pgvector 교체

> **현재**: ChromaDB 직접 의존, `$gte/$lte` 숫자만 지원 (date_int 우회 필요)
> **개선**: DB 교체 시 코드 변경 0줄, 설정만 변경

벡터 DB 인터페이스를 추상화하여 구현체만 교체합니다.

```
현재: retrieval.py → ChromaDB 직접 호출
개선: retrieval.py → VectorStore 인터페이스 → ChromaStore / QdrantStore / PgVectorStore
```

**변경 파일**: `database.py`, `retrieval.py`, `query_analyzer.py`

<details>
<summary>핵심 코드</summary>

```python
class BaseVectorStore(ABC):
    @abstractmethod
    def add(self, ids, documents, embeddings, metadatas): ...

    @abstractmethod
    def query(self, query_embedding, n_results, where=None) -> dict: ...

    @abstractmethod
    def get(self, where=None, include=None) -> dict: ...

    @abstractmethod
    def count(self) -> int: ...

class ChromaVectorStore(BaseVectorStore):
    """ChromaDB 구현 (현재)"""
    ...

class QdrantVectorStore(BaseVectorStore):
    """Qdrant 구현 — 문자열 범위 비교 네이티브 지원"""
    ...

class PgVectorStore(BaseVectorStore):
    """PostgreSQL + pgvector — SQL WHERE 자유도"""
    async def query(self, query_embedding, n_results, where=None):
        sql = """
            SELECT *, embedding <=> $1 AS distance
            FROM chunks
            WHERE date BETWEEN $2 AND $3 AND room = $4
            ORDER BY distance LIMIT $5
        """
```

**대안 DB 비교:**

| DB | 메타데이터 필터 | 날짜 범위 | 로컬 | 특징 |
|----|--------------|----------|------|------|
| ChromaDB (현재) | ✅ | ⚠️ 숫자만 | ✅ | 설치 간편 |
| Qdrant | ✅ | ✅ 문자열 | ✅/Docker | 필터 성능 우수 |
| pgvector | ✅ SQL | ✅ 네이티브 | Docker | SQL 자유도 |
| Milvus | ✅ | ✅ | Docker | 대규모 최적화 |
| Pinecone | ✅ | ✅ | ❌ 클라우드 | 관리형 |

</details>

---

### 5. 멀티 데이터 소스 — CSV, JSON, DB 직접 연결

> **현재**: `[날짜, 시간, 채팅방, 내용, 사용자]` 형식만 지원
> **개선**: CSV, JSON, DB 등 다양한 형식 자동 파싱

데이터 소스별 파서를 플러그인 방식으로 추가합니다.

```
chat_logs.txt → ChatLogParser  ─┐
data.csv      → CSVParser      ─┼→ 표준 형식 → 임베딩
data.json     → JSONParser     ─┤
PostgreSQL    → DBParser       ─┘
```

**변경 파일**: `services/parsers/` (새 디렉토리), `chunking.py`, `documents.py`

<details>
<summary>핵심 코드</summary>

```python
class BaseParser(ABC):
    @abstractmethod
    def parse(self, content: str) -> list[dict]:
        """[{"embedding_text": str, "original": str, "metadata": dict}]"""
        ...

class CSVParser(BaseParser):
    def __init__(self, config: dict):
        self.text_columns = config["text_columns"]       # ["내용"]
        self.filter_columns = config["filter_columns"]    # ["부서", "작성자"]
        self.date_column = config.get("date_column")      # "날짜"

    def parse(self, content: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(content))
        results = []
        for row in reader:
            text = " ".join(row[col] for col in self.text_columns)
            filters = " ".join(row[col] for col in self.filter_columns)
            results.append({
                "embedding_text": f"{filters}: {text}",
                "original": str(row),
                "metadata": {col: row[col] for col in self.filter_columns},
            })
        return results

class ParserFactory:
    @staticmethod
    def create(file_type: str, config=None) -> BaseParser:
        match file_type:
            case "txt":  return ChatLogParser()
            case "csv":  return CSVParser(config)
            case "json": return JSONParser(config)
```

</details>

---

### 6. 사용자 인증 — JWT 기반

> **현재**: 인증 없음 (누구나 API 접근 가능)
> **개선**: JWT 토큰 기반 인증, 사용자별 접근 제어

로그인 → 토큰 발급 → API 호출 시 토큰 검증 방식입니다.

```
현재: 브라우저 → API (인증 없음)
개선: 브라우저 → 로그인 → JWT 발급
      브라우저 → API + Authorization: Bearer {token} → 검증 → 응답
```

**변경 파일**: `app/auth/` (새 디렉토리), `main.py`, `config.py`, `index.html`

<details>
<summary>핵심 코드</summary>

```python
# auth/jwt.py
def create_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "토큰 만료")

# auth/dependencies.py
security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    return verify_token(credentials.credentials)

# api/query.py — 인증 적용
@router.post("/query")
async def query(request: QueryRequest, user=Depends(get_current_user)):
    ...

# api/auth.py — 로그인
@router.post("/auth/login")
async def login(username: str, password: str):
    user = authenticate(username, password)
    if not user:
        raise HTTPException(401, "인증 실패")
    return {"access_token": create_token(user.id), "token_type": "bearer"}
```

**권한 분리:**

| 역할 | 권한 |
|------|------|
| admin | 업로드, 삭제, 질의, 설정 |
| user | 질의만 |

</details>

---

<div align="center">

Built with ❤️ using [FastAPI](https://fastapi.tiangolo.com) + [Ollama](https://ollama.com) + [ChromaDB](https://www.trychroma.com)

</div>
