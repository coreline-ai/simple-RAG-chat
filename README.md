<div align="center">

# 🔍 Simple RAG Chat

**정형 데이터 기반 로컬 RAG 채팅 시스템**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.6-FF6F00?style=for-the-badge)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

외부 API 키 없이, 로컬 LLM만으로 동작하는 RAG(Retrieval-Augmented Generation) 시스템입니다.
**채팅 로그**와 **엑셀 이슈 데이터** 등 정형 데이터에 최적화된 임베딩 전략과 **스마트 쿼리 라우팅**을 제공합니다.

[시작하기](#-빠른-시작) · [아키텍처](#-아키텍처) · [데이터 형식](#-지원-데이터-형식) · [API](#-api)

</div>

---

## ✨ 주요 특징

| 특징 | 설명 |
|------|------|
| 🔒 **완전 로컬 실행** | Ollama 기반, API 키 불필요, 데이터 외부 유출 없음 |
| 🧠 **스마트 쿼리 분석** | 규칙 기반 분석기 + kiwipiepy 형태소 분석으로 질의 의도를 <1ms로 자동 분류 |
| 🔄 **4가지 검색 전략** | vector / metadata / hybrid / aggregate 자동 라우팅 |
| 📊 **멀티 데이터 소스** | 채팅 로그(TXT) + 엑셀 이슈 데이터(XLSX) 지원, 파서 팩토리로 확장 가능 |
| 🏷️ **행동 라벨링 + KSS** | 엑셀 이슈의 서술형 분석 텍스트를 행동 단위로 분할하여 검색 정확도 향상 |
| 💾 **임베딩 캐시** | LRU 캐시로 중복 임베딩 방지, 2회차부터 <0.1ms |
| 🌐 **LLM 팩토리** | Ollama / Claude / Codex 프록시를 `.env` 한 줄로 전환 |
| ⚡ **SSE 스트리밍** | 토큰 단위 실시간 스트리밍으로 체감 응답 시간 95% 개선 |
| 🌙 **채팅 UI** | 다크 테마, LLM 상태 표시, 출처 접기/펼치기 |
| 📝 **한글 우선** | 코드 주석, 응답, 로그 모두 한글 |

---

## 🚀 빠른 시작

### 사전 요구사항

- **Python** 3.11+
- **Ollama** ([설치 가이드](https://ollama.com/download))
- 선택 사항: Codex/Claude 프록시 서버

> 임베딩은 항상 Ollama를 사용하므로, 프록시 모드여도 `bge-m3`는 필요합니다.

### 1. 모델 설치

```bash
ollama pull bge-m3              # 임베딩 모델 (한국어 지원 다국어)
ollama pull qwen2.5-coder:7b    # LLM 모델
```

### 2. 프로젝트 설정

```bash
git clone https://github.com/coreline-ai/simple-RAG-chat.git
cd simple-RAG-chat
pip install -r requirements.txt
cp .env.example .env            # 필요 시 설정 수정
```

### 3. 데이터 생성 & 업로드

```bash
python generate_data.py         # 샘플 데이터 생성
python upload_data.py           # 임베딩 + ChromaDB 저장
```

### 4. 서버 실행

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 포트 충돌 시 `--port 8001` 등 다른 포트 사용 가능

### 5. 접속

| 주소 | 설명 |
|------|------|
| http://localhost:8000 | 💬 채팅 UI |
| http://localhost:8000/docs | 📖 Swagger API 문서 |
| http://localhost:8000/health | 🏥 서버 상태 |
| http://localhost:8000/health/llm | 🤖 LLM provider/model 상태 |

---

## 🏗 아키텍처

```
┌──────────────────────────────────────────────────┐
│                  채팅 UI (브라우저)                 │
│               app/static/index.html               │
└────────────────────┬─────────────────────────────┘
                     │ HTTP (JSON / SSE)
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
          ┌──────▼──────┐ ┌────▼──────────┐
          │   Ollama    │ │  LLM Factory  │
          │   bge-m3    │ │  Ollama /     │
          │  (임베딩)    │ │  Claude /     │
          │             │ │  Codex        │
          └──────┬──────┘ └───────────────┘
                 │
          ┌──────▼──────┐
          │  ChromaDB   │
          │ (벡터 저장)  │
          └─────────────┘
```

### 검색 파이프라인

```
사용자 질의
    │
    ▼
[1단계] 쿼리 분석 (규칙 기반 + kiwipiepy, <1ms)
    ├─ 날짜 추출: "2024-02-21", "3월", "최근"
    ├─ 담당자/사용자 매칭: DB에서 동적 조회
    ├─ 상태 감지: 완료/진행중/대기
    ├─ 의도 분류: search / summary / list / aggregate
    └─ 전략 결정: vector / metadata / hybrid / aggregate
    │
    ▼
[2단계] 스마트 검색 + LLM 답변 생성
    ├─ 전략에 따른 ChromaDB 검색
    ├─ 결과 그룹핑 + 시간순 정렬
    └─ LLM 답변 생성 (JSON 또는 SSE 스트리밍)
    │
    ▼
응답 (answer + sources)
```

---

## 📊 지원 데이터 형식

### 1. 채팅 로그 (TXT)

```
[날짜, 시간, 채팅방이름, 입력내용, 사용자]
```

```
[2024-02-21, 14:30:00, 백엔드개발, 서버 배포 3차 완료했습니다, 김민수]
[2024-02-21, 14:31:00, 백엔드개발, 수고하셨습니다!, 박서준]
```

**청킹 전략:** 1줄 = 1임베딩, 메시지 내 쉼표 보존

### 2. 엑셀 이슈 데이터 (XLSX)

엑셀 컬럼:

| 컬럼 | 설명 |
|------|------|
| 모델 이슈 검토 사항 | 이슈 제목 |
| 등록일 | 이슈 등록 날짜 |
| 기본 확인내용 | 초기 조사 결과 |
| 기본 작업내용 | 수행한 작업 |
| 업무지시 | 관리자 지시사항 |
| 담당자 | 이슈 담당자 |
| 업무시작일 / 완료예정 | 기간 |
| 진행(담당자) | 현재 상태 |
| 완료일 | 완료 날짜 |
| 문제 원인 분석 결과 | 서술형 상세 분석 |

**청킹 전략:**
- **1차:** 1 row = 1 사건 = 1 chunk (Row Chunking)
- **2차:** 600자 초과 시 KSS(Korean Sentence Splitter)로 행동 단위 분할
- **라벨링:** 서술형 분석 텍스트를 `[근본 원인]`, `[확인 근거]`, `[영향 판단]`, `[현장 영향]`, `[추가 조치]`로 자동 라벨링

### 임베딩 텍스트 설계

**채팅 로그:**
```
"백엔드개발 김민수: 서버 배포 3차 완료했습니다"
```

**엑셀 이슈:**
```
[이슈] GPU 메모리 부족 발생
[등록일] 2025-03-01
[기본 확인내용] 대규모 병렬 처리 시 worker 비가동 및 OOM 로그 확인
[기본 작업내용] batch size 조정, 최대 토큰 길이 제한
[업무지시] 대규모 요청 제한안과 graceful degradation 정책 마련
[담당자] Sujin
[진행] 진행중
[문제 원인 분석 결과] 근본 원인: 단일 시점 요청이 몰리며...
```

### 메타데이터 스키마

| 필드 | 채팅 로그 | 엑셀 이슈 | 용도 |
|------|----------|----------|------|
| `date` | ✅ | ✅ `created_at_iso` | 날짜 정확 매칭 |
| `date_int` | ✅ | ✅ `created_at_int` | 날짜 범위 비교 |
| `room` | ✅ | - | 채팅방 필터 |
| `user` | ✅ | - | 사용자 필터 |
| `assignee` | - | ✅ | 담당자 필터 |
| `status` | - | ✅ | 상태 필터 (완료/진행중) |
| `doc_type` | - | ✅ `issue` | 데이터 유형 |
| `split_index` | - | ✅ | 2차 분할 인덱스 |

---

## 🔎 지원 질의 유형

| 유형 | 예시 | 검색 전략 |
|------|------|----------|
| 📄 **내용 검색** | "서버 배포 관련 이슈 찾아줘" | `vector` |
| 📅 **날짜 검색** | "2025-03-01 일어난 일을 요약해줘" | `hybrid` |
| 📅 **날짜 범위** | "3월 이슈를 보여줘" | `hybrid` |
| 👤 **담당자 검색** | "Sujin 담당 이슈는?" | `metadata` |
| 📋 **상태 필터** | "완료된 이슈 목록" | `aggregate` |
| 🏠 **채팅방 검색** | "AI연구팀에서 어떤 대화를 했나요?" | `metadata` |
| 📊 **통계/집계** | "가장 많은 이슈를 처리한 담당자는?" | `aggregate` |
| 🔀 **복합 필터** | "3월에 Sujin이 완료한 이슈" | `hybrid` |
| ⏰ **상대 날짜** | "최근 이슈", "이번 주 완료 건" | `hybrid` |
| 📝 **요약** | "GPU 관련 문제 원인 분석 요약" | `hybrid` |

---

## ⚙️ LLM 모드 설정

### Ollama 모드 (기본값)

```env
LLM_PROVIDER=ollama
LLM_MODEL=qwen2.5-coder:7b
EMBEDDING_MODEL=bge-m3
```

### Codex 프록시 모드

```env
LLM_PROVIDER=codex
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CODEX_MODEL=gpt-5-codex
```

### Claude 프록시 모드

```env
LLM_PROVIDER=claude
PROXY_API_URL=http://localhost:8080
PROXY_API_KEY=your-cli-proxy-api-key
CLAUDE_MODEL=claude-sonnet-latest
```

> 프록시 모드에서도 임베딩은 Ollama `bge-m3`를 사용합니다.

---

## 📁 프로젝트 구조

```
simple-RAG-chat/
├── app/
│   ├── main.py                    # FastAPI 앱 진입점, 정적 파일, 헬스체크
│   ├── config.py                  # 환경 설정 (Pydantic Settings)
│   ├── database.py                # ChromaDB + documents.json 저장소
│   ├── schemas.py                 # Pydantic 요청/응답 스키마
│   ├── api/
│   │   ├── documents.py           # 문서 CRUD API
│   │   └── query.py               # 질의 응답 + SSE 스트리밍 API
│   ├── services/
│   │   ├── chunking.py            # 하위 호환 래퍼 (parsers/ 위임)
│   │   ├── embedding.py           # Ollama 임베딩 (bge-m3, 캐시 지원)
│   │   ├── embedding_cache.py     # LRU 임베딩 캐시
│   │   ├── query_analyzer.py      # 규칙 기반 쿼리 분석 + kiwipiepy
│   │   ├── retrieval.py           # 4가지 검색 전략 라우터
│   │   ├── llm.py                 # LLM 팩토리 (Ollama/Proxy)
│   │   ├── parsers/
│   │   │   ├── base.py            # BaseParser 인터페이스
│   │   │   ├── factory.py         # ParserFactory (파일 확장자 자동 감지)
│   │   │   ├── chat_log_parser.py # 채팅 로그 파서
│   │   │   ├── excel_issue_parser.py  # 엑셀 이슈 파서 (KSS + 라벨링)
│   │   │   └── labeler.py         # 행동 라벨링 엔진
│   │   └── vector_stores/
│   │       ├── base.py            # BaseVectorStore 인터페이스
│   │       ├── chroma_store.py    # ChromaDB 구현체
│   │       └── factory.py         # VectorStoreFactory
│   └── static/
│       └── index.html             # 채팅 UI (다크 테마, SSE 스트리밍)
├── data/
│   ├── base/
│   │   └── chat_logs.txt          # 채팅 로그 샘플
│   └── model_issue_dataset_10000.xlsx  # 엑셀 이슈 데이터
├── docs/
│   ├── PRD.md                     # 제품 요구사항 정의서
│   └── TRD.md                     # 기술 참조 문서
├── tests/
│   ├── test_chunking.py           # 청킹 단위 테스트
│   ├── test_query_analyzer.py     # 쿼리 분석기 테스트
│   ├── test_documents.py          # 문서 API 테스트
│   └── test_llm_proxy.py          # 프록시 LLM 테스트
├── generate_data.py               # 샘플 데이터 생성기
├── upload_data.py                 # 일괄 임베딩 업로드
├── requirements.txt               # Python 의존성
└── .env.example                   # 환경 변수 템플릿
```

---

## 🛠 기술 스택

| 분류 | 기술 | 역할 |
|------|------|------|
| **프레임워크** | FastAPI 0.115 | REST API + SSE 스트리밍 서버 |
| **벡터 DB** | ChromaDB 0.6 | 벡터 + 메타데이터 저장 |
| **임베딩** | bge-m3 (Ollama) | 한국어 지원 다국어 임베딩 (1024d) |
| **LLM** | qwen2.5-coder:7b / Claude / Codex | 답변 생성 (팩토리 패턴) |
| **한국어 NLP** | kss, kiwipiepy | 문장 분리 + 형태소 분석 |
| **HTTP** | httpx 0.28 | 비동기 Ollama/프록시 통신 |
| **엑셀** | openpyxl | XLSX 파싱 |
| **프론트엔드** | Vanilla JS | 의존성 없는 채팅 UI |

---

## 📡 API

### 질의 응답

**`POST /query`** — JSON 응답

```json
{
    "question": "GPU 메모리 관련 이슈 원인은?",
    "top_k": 5
}
```

**`POST /query/stream`** — SSE 스트리밍 응답 (UI 기본)

### 문서 관리

| Method | Endpoint | 설명 |
|--------|----------|------|
| `POST` | `/documents` | 텍스트 업로드 |
| `POST` | `/documents/upload-file` | 파일 업로드 |
| `GET` | `/documents` | 문서 목록 |
| `DELETE` | `/documents/{id}` | 문서 삭제 |

### 상태 확인

| Method | Endpoint | 설명 |
|--------|----------|------|
| `GET` | `/health` | 서버 상태 |
| `GET` | `/health/llm` | LLM provider/model/상태 |

---

## 🧪 테스트

```bash
pytest -q
```

테스트 범위:
- 채팅 로그 파싱과 `date_int` 생성
- 사용자 이름 오탐 방지 및 상대 날짜 해석
- 문서 삭제 API 동작
- 프록시 LLM 인증 헤더, 직렬화, 재시도, 스트리밍 오류 처리

---

## 🔧 주요 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama 서버 주소 |
| `LLM_MODEL` | `qwen2.5-coder:7b` | Ollama 모드 답변 모델 |
| `EMBEDDING_MODEL` | `bge-m3` | Ollama 임베딩 모델 |
| `LLM_PROVIDER` | `ollama` | `ollama` / `claude` / `codex` |
| `PROXY_API_URL` | `http://localhost:8080` | OpenAI 호환 프록시 주소 |
| `PROXY_API_KEY` | 빈 값 | 프록시 Bearer 토큰 |
| `CLAUDE_MODEL` | `claude-sonnet-latest` | Claude 프록시 모델명 |
| `CODEX_MODEL` | `gpt-5-codex` | Codex 프록시 모델명 |
| `VECTOR_DB_TYPE` | `chroma` | 벡터 저장소 타입 |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Chroma 저장 경로 |
| `CHUNKING_STRATEGY` | `line` | `line` / `session` / `kss` |
| `EXCEL_ROW_MAX_CHARS` | `600` | 엑셀 2차 KSS 분할 임계값 |
| `USE_KIWI_KEYWORDS` | `true` | kiwipiepy 형태소 분석 사용 |
| `EMBEDDING_CACHE_ENABLED` | `true` | 임베딩 LRU 캐시 활성화 |
| `TOP_K` | `5` | 기본 검색 결과 수 |

---

## 🐛 트러블슈팅

### 포트 충돌 (`Errno 10048`)
```bash
# Windows
powershell -Command "Get-Process python | Stop-Process -Force"
# 또는 다른 포트 사용
uvicorn app.main:app --port 8001
```

### 프록시 연결됐는데 답변 실패
- `/health/llm`의 `configured_model`이 `/v1/models`에 있는지 확인
- `unknown provider for model ...` → 프록시 alias 또는 upstream 설정 문제

### 프록시 모드에서 임베딩 실패
- 프록시는 답변 생성 전용. 임베딩은 Ollama `bge-m3` 필수

### `favicon.ico` 404
- UI는 인라인 favicon 사용. 브라우저 강제 새로고침으로 해결

---

## 📚 문서

| 문서 | 설명 |
|------|------|
| [PRD](docs/PRD.md) | 제품 요구사항 정의서 |
| [TRD](docs/TRD.md) | 기술 참조 문서 |
| [CLAUDE.md](CLAUDE.md) | 프로젝트 작업 원칙 |

---

<div align="center">

Built with ❤️ using [FastAPI](https://fastapi.tiangolo.com) + [Ollama](https://ollama.com) + [ChromaDB](https://www.trychroma.com)

</div>
