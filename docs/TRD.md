# TRD — RAG-Text-LLM 기술 참조 문서

**문서 버전**: 1.0
**작성일**: 2026-03-24
**상태**: 구현 완료 (v1.0)

---

## 1. 시스템 아키텍처

### 1.1 전체 구조

```
┌─────────────────────────────────────────────────────────────┐
│                     클라이언트 (브라우저)                       │
│                    app/static/index.html                     │
│                  [다크 테마 채팅 UI]                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTP (JSON)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI 서버 (포트 8000)                      │
│                      app/main.py                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  /documents   │  │   /query     │  │   /health    │       │
│  │  documents.py │  │   query.py   │  │   main.py    │       │
│  └──────┬───────┘  └──────┬───────┘  └──────────────┘       │
│         │                  │                                  │
│  ┌──────▼───────────────────▼─────────────────────────┐      │
│  │              서비스 레이어 (services/)                │      │
│  │  ┌──────────┐ ┌──────────────┐ ┌──────────────┐   │      │
│  │  │chunking  │ │query_analyzer│ │  retrieval   │   │      │
│  │  │파싱+청킹  │ │쿼리 분석 <1ms│ │4가지 검색전략 │   │      │
│  │  └──────────┘ └──────────────┘ └──────┬───────┘   │      │
│  │  ┌──────────┐                  ┌──────▼───────┐   │      │
│  │  │embedding │                  │     llm      │   │      │
│  │  │벡터 생성  │                  │  답변 생성    │   │      │
│  │  └────┬─────┘                  └──────┬───────┘   │      │
│  └───────┼───────────────────────────────┼───────────┘      │
└──────────┼───────────────────────────────┼──────────────────┘
           │                               │
     ┌─────▼─────┐                   ┌─────▼─────┐
     │  Ollama   │                   │  Ollama   │
     │ bge-m3   │                   │ qwen2.5-  │
     │(임베딩)   │                   │ coder:7b  │
     │ :11434   │                   │ (LLM)     │
     └─────┬─────┘                   └───────────┘
           │
     ┌─────▼─────┐
     │ ChromaDB  │
     │(벡터 저장) │
     │ 파일 기반  │
     └───────────┘
```

### 1.2 레이어 구조

```
┌─────────────────────────────────────────┐
│  프레젠테이션 레이어                       │
│  app/static/index.html (채팅 UI)         │
│  app/api/documents.py (문서 API)         │
│  app/api/query.py (질의 API)             │
├─────────────────────────────────────────┤
│  스키마 레이어                            │
│  app/schemas.py (Pydantic 모델)          │
├─────────────────────────────────────────┤
│  비즈니스 로직 레이어                      │
│  app/services/chunking.py (파싱/청킹)    │
│  app/services/query_analyzer.py (분석)   │
│  app/services/retrieval.py (검색)        │
│  app/services/embedding.py (임베딩)      │
│  app/services/llm.py (LLM 답변)         │
├─────────────────────────────────────────┤
│  데이터 레이어                            │
│  app/database.py (ChromaDB + JSON)      │
│  app/config.py (설정)                    │
├─────────────────────────────────────────┤
│  인프라 레이어                            │
│  Ollama (로컬 LLM/임베딩 서버)           │
│  ChromaDB (벡터 저장소)                   │
└─────────────────────────────────────────┘
```

---

## 2. 기술 스택 상세

### 2.1 핵심 의존성

| 패키지 | 버전 | 역할 | 라이선스 |
|--------|------|------|---------|
| fastapi | 0.115.6 | 웹 프레임워크 | MIT |
| uvicorn[standard] | 0.34.0 | ASGI 서버 | BSD |
| chromadb | 0.6.3 | 벡터 DB | Apache 2.0 |
| httpx | 0.28.1 | 비동기 HTTP | BSD |
| pydantic | 2.10.4 | 데이터 검증 | MIT |
| pydantic-settings | 2.7.0 | 환경 설정 | MIT |
| python-dotenv | 1.0.1 | .env 로드 | BSD |
| python-multipart | 0.0.20 | 파일 업로드 | Apache 2.0 |

### 2.2 개발/테스트 의존성

| 패키지 | 버전 | 역할 |
|--------|------|------|
| pytest | 8.3.4 | 단위 테스트 |
| pytest-asyncio | 0.25.0 | 비동기 테스트 |

### 2.3 외부 서비스

| 서비스 | 버전 | 포트 | 모델 |
|--------|------|------|------|
| Ollama | latest | 11434 | bge-m3 (임베딩), qwen2.5-coder:7b (LLM) |

---

## 3. 데이터 모델

### 3.1 ChromaDB 컬렉션 스키마

**컬렉션명**: `rag_chunks`

| 필드 | 타입 | 저장 위치 | 용도 |
|------|------|----------|------|
| id | string | ids | 고유 식별자 (`{doc_id}_line_{index}`) |
| document | string | documents | 임베딩 텍스트 ("채팅방 사용자: 내용") |
| embedding | float[] | embeddings | 1024차원 벡터 (bge-m3) |
| document_id | string | metadatas | 소속 문서 ID |
| chunk_index | int | metadatas | 라인 순서 번호 |
| filename | string | metadatas | 원본 파일명 |
| room | string | metadatas | 채팅방 이름 (필터용) |
| user | string | metadatas | 사용자 이름 (필터용) |
| date | string | metadatas | 날짜 YYYY-MM-DD (정확 매칭용) |
| date_int | int | metadatas | 날짜 정수 YYYYMMDD (범위 비교용) |
| time | string | metadatas | 시간 HH:MM:SS (정렬용) |
| original | string | metadatas | 원본 라인 텍스트 |

### 3.2 문서 메타데이터 (JSON)

**파일**: `chroma_db/documents.json`

```json
{
    "doc_uuid": {
        "filename": "chat_logs.txt",
        "total_chunks": 10000,
        "created_at": "2026-03-24T00:00:00Z"
    }
}
```

### 3.3 데이터 크기 추정

| 항목 | 값 |
|------|-----|
| 1건당 임베딩 텍스트 | ~50 바이트 |
| 1건당 벡터 크기 | 1024 × 4 = 4,096 바이트 |
| 1건당 메타데이터 | ~300 바이트 |
| 10,000건 총 크기 | ~44 MB (벡터) + ~3.5 MB (메타) |
| ChromaDB 디스크 사용 | ~100 MB (인덱스 포함) |

---

## 4. 핵심 알고리즘

### 4.1 쿼리 분석 파이프라인

```
입력: "2024년 3월에 개발팀에서 서버 배포한 기록"
                    │
    ┌───────────────▼───────────────┐
    │  Step 1: 날짜 추출            │
    │  "2024년 3월" →               │
    │    date_from: "2024-03-01"   │
    │    date_to:   "2024-03-31"   │
    │  clean_query: "개발팀에서     │
    │    서버 배포한 기록"           │
    └───────────────┬───────────────┘
                    │
    ┌───────────────▼───────────────┐
    │  Step 2: 채팅방 매칭          │
    │  "개발팀" → room: "개발팀"   │
    │  clean_query: "서버 배포한    │
    │    기록"                      │
    └───────────────┬───────────────┘
                    │
    ┌───────────────▼───────────────┐
    │  Step 3: 사용자 이름 감지     │
    │  (매칭 없음)                  │
    └───────────────┬───────────────┘
                    │
    ┌───────────────▼───────────────┐
    │  Step 4: 의도 분류            │
    │  키워드 매칭 → intent=search  │
    └───────────────┬───────────────┘
                    │
    ┌───────────────▼───────────────┐
    │  Step 5: 전략 결정            │
    │  필터 있음 + 키워드 있음      │
    │  → strategy: "hybrid"        │
    └───────────────┬───────────────┘
                    │
출력: QueryAnalysis(
    intent=search,
    strategy=hybrid,
    filters={room: "개발팀",
             date_from: "2024-03-01",
             date_to: "2024-03-31"},
    search_text="서버 배포한 기록"
)
```

### 4.2 검색 전략 라우팅

```
QueryAnalysis
    │
    ├─ strategy == "vector"
    │   → 벡터 유사도 검색
    │   → query_embeddings + n_results=top_k*3
    │
    ├─ strategy == "metadata"
    │   → ChromaDB where 필터
    │   → 시간순 정렬
    │   → 결과 0건이면 vector 폴백
    │
    ├─ strategy == "hybrid"
    │   → where 필터 + query_embeddings
    │   → 필터 0건이면 vector 폴백
    │   → 채팅방별 그룹핑
    │
    └─ strategy == "aggregate"
        → 전체 데이터 로드 (where 필터 적용)
        → 채팅방별/사용자별 카운트
        → 통계 요약 + 균일 샘플링
```

### 4.3 ChromaDB 필터 변환

```python
# 정확한 날짜 → 문자열 정확 매칭
{"date": "2024-02-21"}

# 날짜 범위 → 정수 비교 (ChromaDB $gte/$lte 제약)
{"$and": [
    {"date_int": {"$gte": 20240301}},
    {"date_int": {"$lte": 20240331}}
]}

# 복합 필터
{"$and": [
    {"room": "개발팀"},
    {"date_int": {"$gte": 20240301}},
    {"date_int": {"$lte": 20240331}}
]}
```

### 4.4 한국어 이름 감지 알고리즘

```python
# 패턴: 성(1자) + 이름(2자) + 조사 lookahead
regex = r"(김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|류|홍)"
        r"[가-힣]{2}"
        r"(?=이|가|의|는|을|를|에게|한테|님|\s|$)"

# 오탐 방지: 블랙리스트
_NOT_NAMES = {
    "이름을", "이름이", "이름은",  # "이" + "름을" 매칭 방지
    "이번에", "이전에", "이후에",
    "임원회", "임원회의",
    ...
}

# 매칭 후 확장 검사: name + 뒤 1글자까지 블랙리스트 확인
```

---

## 5. API 상세 명세

### 5.1 POST /query

**요청**
```json
{
    "question": "string (필수)",
    "top_k": "int (선택, 기본값: 5)"
}
```

**응답 (200)**
```json
{
    "question": "string",
    "answer": "string",
    "sources": [
        {
            "id": "string",
            "chunk_index": "int",
            "content": "string",
            "score": "float (0~1)"
        }
    ]
}
```

**내부 처리 흐름**
```
1. QueryRequest 검증 (Pydantic)
2. search_similar_chunks(question, top_k)
   2a. analyze_query(question) → QueryAnalysis (<1ms)
   2b. 전략별 검색 실행 (~200ms)
3. 컨텍스트 조합 (500자/청크 제한)
4. 의도 힌트 추가
5. llm.generate(prompt, context) (~15-210초)
6. QueryResponse 반환
```

### 5.2 POST /documents

**요청**
```json
{
    "filename": "string (필수)",
    "content": "string (필수)"
}
```

**내부 처리 흐름**
```
1. 텍스트 → parse_and_format_lines()
2. 배치 50건 → get_embeddings()
3. ChromaDB chunks_collection.add()
4. documents.json 메타데이터 저장
```

### 5.3 GET /health

**응답**
```json
{
    "status": "ok",
    "service": "RAG-Text-LLM"
}
```

---

## 6. 설정 명세

### 6.1 환경 변수

| 변수명 | 타입 | 기본값 | 설명 |
|--------|------|--------|------|
| OLLAMA_BASE_URL | str | http://localhost:11434 | Ollama 서버 URL |
| LLM_MODEL | str | qwen2.5-coder:7b | LLM 모델 이름 |
| EMBEDDING_MODEL | str | bge-m3 | 임베딩 모델 이름 |
| CHROMA_PERSIST_DIR | str | ./chroma_db | ChromaDB 저장 경로 |
| CHUNK_SIZE | int | 20 | 청크 크기 (라인 수) |
| CHUNK_OVERLAP | int | 5 | 청크 겹침 (라인 수) |
| TOP_K | int | 5 | 검색 결과 수 |

### 6.2 서버 설정

```json
// .claude/launch.json
{
    "version": "0.0.1",
    "configurations": [{
        "name": "rag-server",
        "runtimeExecutable": "python",
        "runtimeArgs": ["-m", "uvicorn", "app.main:app",
                        "--host", "0.0.0.0", "--port", "8000"],
        "port": 8000,
        "cwd": "RAG-Text-LLM"
    }]
}
```

---

## 7. 임베딩 전략 상세

### 7.1 청킹 전략 비교 (결정 근거)

| 전략 | 검색 정확도 | 구현 | 채택 |
|------|-----------|------|------|
| 고정 크기 (20줄) | ❌ 낮음 (채팅방 혼합) | 간단 | ✗ |
| 채팅방별 그룹핑 | △ 보통 (문맥 유지) | 중간 | ✗ |
| **1줄 = 1임베딩** | ✅ 높음 (정밀 검색) | 메타데이터 활용 | ✓ |

**선택 이유**: 정형 데이터에서 각 행은 독립적인 의미 단위. 메타데이터 필터로
채팅방/사용자/날짜를 정확히 필터링할 수 있어 1줄 단위가 최적.

### 7.2 임베딩 텍스트 설계

```
# 나쁜 예 (내용만)
"서버 배포 3차 완료했습니다"
→ "개발팀 배포"로 검색 시 매칭 실패

# 좋은 예 (보강 필드 포함)
"백엔드개발 김민수: 서버 배포 3차 완료했습니다"
→ "개발" 키워드가 임베딩에 포함되어 매칭 성공
```

### 7.3 임베딩 모델 비교 (결정 근거)

| 모델 | 한국어 | 차원 | 속도 | 채택 |
|------|--------|------|------|------|
| nomic-embed-text | ⚠️ 약함 | 768 | 빠름 | ✗ (한국어 성능 부족) |
| **bge-m3** | ✅ 우수 | 1024 | 보통 | ✓ |
| text-embedding-3-small | ✅ 우수 | 1536 | 빠름 | ✗ (API 키 필요) |

---

## 8. 프론트엔드 기술 명세

### 8.1 구성

| 항목 | 사양 |
|------|------|
| 프레임워크 | Vanilla JS (의존성 없음) |
| 스타일링 | 인라인 CSS (다크 테마) |
| API 통신 | Fetch API |
| 배포 | FastAPI StaticFiles 마운트 |

### 8.2 색상 팔레트

| 용도 | 색상 코드 |
|------|----------|
| 배경 | #1a1a2e |
| 헤더 | #16213e |
| 입력 영역 | #0f3460 |
| 강조 (빨강) | #e94560 |
| 사용자 메시지 | #0f3460 |
| 봇 메시지 | #16213e |
| 텍스트 | #eee |
| 보조 텍스트 | #aaa |

### 8.3 핵심 자바스크립트 함수

```javascript
// API 베이스 URL (상대 경로)
const API = '';

// 질의 전송
async sendQuestion() {
    POST /query → {question, top_k: 5}
    → addBotMessage(answer, sources)
}

// 봇 메시지 렌더링
addBotMessage(answer, sources) {
    → 답변 텍스트 + 출처 접기/펼치기 UI
    → 각 출처: score, content, chunk_index
}
```

---

## 9. 테스트 명세

### 9.1 단위 테스트

| 테스트 파일 | 대상 모듈 | 테스트 수 |
|------------|----------|----------|
| test_chunking.py | chunking.py | 8개 |

### 9.2 테스트 커버리지

| 모듈 | 커버리지 | 비고 |
|------|---------|------|
| chunking.py | ~80% | 파싱, 분할, 그룹핑 |
| query_analyzer.py | 0% | 테스트 미작성 |
| retrieval.py | 0% | Ollama 의존으로 mock 필요 |
| embedding.py | 0% | Ollama 의존 |
| llm.py | 0% | Ollama 의존 |

### 9.3 수동 테스트 결과 (5가지 질의 유형)

| # | 질의 | 전략 | 결과 |
|---|------|------|------|
| 1 | "2024-02-21 일어난 일" | hybrid | ✅ 해당 날짜 10건 반환, 요약 정확 |
| 2 | "AI연구팀 팀원 이름" | aggregate | ✅ 14명 나열 |
| 3 | "김민수가 뭐 했어?" | hybrid | ✅ 사용자 필터 적용 |
| 4 | "서버 배포 관련 대화" | vector | ✅ 관련 대화 검색 |
| 5 | "2024년 3월 개발팀 작업" | hybrid | ✅ 복합 필터 적용 |

---

## 10. 디렉토리 구조

```
RAG-Text-LLM/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI 앱 (CORS, 라우터, 정적 파일)
│   ├── config.py               # Settings (pydantic-settings)
│   ├── database.py             # ChromaDB 클라이언트 + JSON 저장소
│   ├── models.py               # 딕셔너리 기반 모델
│   ├── schemas.py              # Pydantic 요청/응답 스키마
│   ├── api/
│   │   ├── __init__.py
│   │   ├── documents.py        # 문서 CRUD API
│   │   └── query.py            # 질의 응답 API
│   ├── services/
│   │   ├── __init__.py
│   │   ├── chunking.py         # 채팅 로그 파싱 + 청킹
│   │   ├── embedding.py        # Ollama 임베딩 생성
│   │   ├── query_analyzer.py   # 규칙 기반 쿼리 분석
│   │   ├── retrieval.py        # 스마트 검색 (4전략)
│   │   └── llm.py              # Ollama LLM 답변 생성
│   └── static/
│       └── index.html          # 채팅 UI
├── tests/
│   ├── __init__.py
│   └── test_chunking.py        # 청킹 단위 테스트
├── data/
│   ├── chat_logs.txt           # 1만건 샘플 데이터
│   └── chat_logs_100.txt       # 100건 테스트 데이터
├── chroma_db/                  # ChromaDB 영구 저장소
├── docs/
│   ├── PRD.md                  # 제품 요구사항 정의서
│   └── TRD.md                  # 기술 참조 문서 (본 문서)
├── generate_data.py            # 데이터 생성기
├── upload_data.py              # 일괄 업로드 스크립트
├── requirements.txt            # Python 의존성
├── .env.example                # 환경 변수 템플릿
└── CLAUDE.md                   # 프로젝트 규칙
```

---

## 11. 배포 및 실행

### 11.1 로컬 실행

```bash
# 1. Ollama 모델 설치
ollama pull bge-m3
ollama pull qwen2.5-coder:7b

# 2. Python 의존성 설치
cd RAG-Text-LLM
pip install -r requirements.txt

# 3. 데이터 생성 + 업로드
python generate_data.py        # 1만건 생성
python upload_data.py          # 임베딩 + 저장 (~18분)

# 4. 서버 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 5. 접속
# 채팅 UI: http://localhost:8000
# Swagger: http://localhost:8000/docs
```

### 11.2 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| RAM | 8 GB | 16 GB |
| 디스크 | 10 GB | 20 GB |
| CPU | 4코어 | 8코어 |
| GPU | 없음 | NVIDIA 8GB+ (Ollama 가속) |
| Python | 3.11 | 3.13 |
