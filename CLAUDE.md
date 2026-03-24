# Simple RAG Chat

정형 채팅 로그를 위한 FastAPI 기반 RAG 프로젝트다.

## 작업 원칙

- 기본 응답과 주석은 한글 우선
- 구현 기준으로 문서를 유지
- 추측보다 실제 저장된 메타데이터와 테스트를 우선

## 현재 기술 스택

- Python 3.11+
- FastAPI
- ChromaDB
- Ollama `bge-m3` 임베딩
- LLM provider
  - `ollama`: `qwen2.5-coder:7b`
  - `claude`: OpenAI 호환 프록시 경유
  - `codex`: OpenAI 호환 프록시 경유

## 핵심 구조

```text
app/
  api/
    documents.py      문서 업로드/조회/삭제
    query.py          일반/스트리밍 질의
  services/
    chunking.py       채팅 로그 파싱, date_int 생성
    embedding.py      Ollama 임베딩
    query_analyzer.py 규칙 기반 질의 분석
    retrieval.py      vector / metadata / hybrid / aggregate 검색
    llm.py            OllamaLLM, ProxyLLM, /health/llm 상태 확인
    vector_stores/    벡터 저장소 추상화
  config.py           Settings
  database.py         ChromaDB + documents.json
  main.py             FastAPI 앱, 정적 파일, 상태 엔드포인트
  static/index.html   단일 페이지 채팅 UI
tests/
  test_chunking.py
  test_query_analyzer.py
  test_documents.py
  test_llm_proxy.py
```

## 데이터 규칙

- 입력 형식: `[날짜, 시간, 채팅방이름, 입력내용, 사용자]`
- 메시지 본문 안의 쉼표는 허용
- 1줄 = 1임베딩
- 메타데이터에는 `room`, `user`, `date`, `date_int`, `time`, `original` 저장

## 검색 규칙

- 채팅방/사용자 목록은 DB에서 동적으로 추출
- 이름 추출은 패턴 추측이 아니라 실제 사용자 목록 매칭
- 날짜 범위는 `date_int`로 필터링
- 상대 날짜는 데이터 최신 날짜를 기준으로 계산

## 실행 메모

```bash
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 upload_data.py
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

포트 충돌이 있으면 `8001`로 올려도 된다.

## 상태 확인

- `GET /health`
- `GET /health/llm`

`/health/llm`은 현재 provider, configured model, 모델 목록, 경고를 반환한다.
