<div align="center">

# 🔍 Simple RAG Chat

**정형 데이터 기반 로컬 RAG 채팅 시스템**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge&logo=ollama&logoColor=white)](https://ollama.com)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.6-FF6F00?style=for-the-badge)](https://www.trychroma.com)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)

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

- [ ] 스트리밍 응답 (SSE) — 체감 응답 시간 개선
- [ ] 임베딩 캐시 — 중복 임베딩 방지
- [ ] LLM 팩토리 패턴 — OpenAI/Claude API 지원
- [ ] 벡터 DB 추상화 — Qdrant/pgvector 교체
- [ ] 멀티 데이터 소스 — CSV, JSON, DB 직접 연결
- [ ] 사용자 인증 — JWT 기반

---

<div align="center">

Built with ❤️ using [FastAPI](https://fastapi.tiangolo.com) + [Ollama](https://ollama.com) + [ChromaDB](https://www.trychroma.com)

</div>
