# RAG-Text-LLM

지식 기반 QA를 위한 RAG(Retrieval-Augmented Generation) 프로젝트

## 규칙

- 모든 출력과 응답은 한글을 우선으로 작성한다
- 코드 주석은 한글로 작성한다
- 커밋 메시지는 한글로 작성한다
- 에러 메시지 및 로그는 한글로 작성한다
- 기술 용어는 원어 병기를 허용한다 (예: 임베딩(Embedding))

## 기술 스택

- **언어**: Python 3.11+
- **프레임워크**: FastAPI
- **임베딩 모델**: text-embedding-3-small (OpenAI 호환)
- **벡터 DB**: PostgreSQL + pgvector
- **ORM**: SQLAlchemy (async) + asyncpg
- **LLM**: 추상 인터페이스 (추후 결정)

## 아키텍처

```
app/
  api/          FastAPI 라우터 (documents, query)
  services/     비즈니스 로직 (chunking, embedding, retrieval, llm)
  config.py     환경 설정
  database.py   DB 연결 관리
  models.py     SQLAlchemy 모델
  schemas.py    Pydantic 스키마
  main.py       앱 진입점
data/           채팅 로그 데이터
tests/          테스트
```

## 데이터 형식

채팅 로그: `[날짜, 시간, 채팅방이름, 입력내용, 사용자]`
