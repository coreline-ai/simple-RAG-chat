"""쿼리 분석기 - 규칙 기반 의도 분류 + 메타데이터 필터 자동 추출

LLM 2회 호출은 로컬 7B 모델에서 너무 느리므로 (30초+30초),
1단계는 빠른 규칙 기반 분석기로 처리하고
2단계(답변 생성)만 LLM에 위임한다.

이 분석기는 질의 패턴을 자동 인식하여:
- 날짜 (YYYY-MM-DD, YYYY년 M월 D일, M월, 최근/이번주 등)
- 날짜 범위 (M월 전체, M월~N월 등)
- 채팅방 이름 (DB에서 동적 조회)
- 사용자 이름 (이름+성씨 패턴 감지)
- 질의 의도 (검색/요약/목록/통계)
- 검색 전략 (vector/metadata/hybrid/aggregate)
을 자동 추출한다.

한국어 최적화:
- kiwipiepy 형태소 분석으로 조사/어미 제거, 핵심 키워드 추출
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from app.config import settings
from app.database import chunks_collection
from app.services.vector_stores.base import VectorStoreFilter


# === kiwipiepy 형태소 분석 (지연 로딩) ===

_kiwi = None

# 제거할 품사: 조사, 어미, 부호
_STOPWORD_POS = {
    "JKS", "JKC", "JKG", "JKO", "JKB", "JKV", "JKQ", "JX", "JC",  # 조사
    "EP", "EF", "EC", "ETN", "ETM",  # 어미
    "SF", "SP", "SS", "SE", "SO",  # 부호
}


def _get_kiwi():
    """kiwipiepy 인스턴스 지연 로딩"""
    global _kiwi
    if _kiwi is None:
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except ImportError:
            _kiwi = False  # 설치 안 된 경우
    return _kiwi


def extract_keywords(text: str) -> str:
    """형태소 분석으로 핵심 키워드 추출 (불용어 제거)

    조사(은/는/이/가), 어미(-했다/-합니다) 등을 제거하여
    벡터 검색의 정밀도를 높인다.
    """
    kiwi = _get_kiwi()
    if not kiwi:
        return text

    try:
        tokens = kiwi.tokenize(text)
        keywords = [t.form for t in tokens if t.tag not in _STOPWORD_POS]
        result = " ".join(keywords)
        return result if result.strip() else text
    except Exception:
        return text


class QueryAnalysis:
    """쿼리 분석 결과"""

    def __init__(self, raw: dict):
        self.intent = raw.get("intent", "search")
        self.filters = raw.get("filters", {})
        self.search_text = raw.get("search_text", "")
        self.strategy = raw.get("strategy", "hybrid")

    @property
    def assignee(self) -> str | None:
        return self._clean(self.filters.get("assignee"))

    @property
    def status(self) -> str | None:
        return self._clean(self.filters.get("status"))

    @property
    def doc_type(self) -> str | None:
        return self._clean(self.filters.get("doc_type"))

    @property
    def room(self) -> str | None:
        return self._clean(self.filters.get("room"))

    @property
    def user(self) -> str | None:
        return self._clean(self.filters.get("user"))

    @property
    def date(self) -> str | None:
        return self._clean(self.filters.get("date"))

    @property
    def date_from(self) -> str | None:
        return self._clean(self.filters.get("date_from"))

    @property
    def date_to(self) -> str | None:
        return self._clean(self.filters.get("date_to"))

    def _clean(self, val) -> str | None:
        if val is None or val == "null" or val == "" or val == "None":
            return None
        return str(val).strip()

    @staticmethod
    def _date_to_int(date_str: str) -> int:
        """날짜 문자열을 정수로 변환 (ChromaDB $gte/$lte는 숫자만 지원)
        '2024-02-21' → 20240221
        """
        return int(date_str.replace("-", ""))

    def to_chroma_where(self) -> dict | None:
        """ChromaDB where 필터 조건 생성

        ChromaDB의 $gte/$lte 연산자는 숫자만 지원하므로,
        날짜 범위 비교는 date_int (정수) 필드를 사용한다.
        정확한 날짜는 date (문자열) 필드로 정확 매칭한다.
        """
        conditions = []

        if self.assignee:
            conditions.append({"assignee": self.assignee})
        if self.status:
            conditions.append({"status": self.status})
        if self.doc_type:
            conditions.append({"doc_type": self.doc_type})
        if self.room:
            conditions.append({"room": self.room})
        if self.user:
            conditions.append({"user": self.user})
        if self.date:
            # 정확한 날짜: 문자열 정확 매칭
            conditions.append({"date": self.date})
        elif self.date_from and self.date_to:
            # 날짜 범위: 정수 필드로 비교
            conditions.append({"date_int": {"$gte": self._date_to_int(self.date_from)}})
            conditions.append({"date_int": {"$lte": self._date_to_int(self.date_to)}})
        elif self.date_from:
            conditions.append({"date_int": {"$gte": self._date_to_int(self.date_from)}})
        elif self.date_to:
            conditions.append({"date_int": {"$lte": self._date_to_int(self.date_to)}})

        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        return {"$and": conditions}

    def to_vector_store_filter(self) -> VectorStoreFilter:
        """벡터 저장소 공통 필터 형식으로 변환

        Returns:
            VectorStoreFilter 인스턴스
        """
        return VectorStoreFilter(
            room=self.room,
            user=self.user,
            date=self.date,
            date_from=self.date_from,
            date_to=self.date_to,
            assignee=self.assignee,
            status=self.status,
            doc_type=self.doc_type,
            document_id=None,
        )

    def __repr__(self):
        return (
            f"QueryAnalysis(intent={self.intent}, strategy={self.strategy}, "
            f"room={self.room}, user={self.user}, date={self.date}, "
            f"date_from={self.date_from}, date_to={self.date_to}, "
            f"search_text='{self.search_text}')"
        )


# === 채팅방 목록 (DB에서 동적 조회 + 캐시) ===
_room_cache: list[str] | None = None
_user_cache: list[str] | None = None
_reference_date_cache: date | None = None


def invalidate_query_analyzer_cache() -> None:
    """쿼리 분석용 메타데이터 캐시 초기화"""
    global _room_cache, _user_cache, _reference_date_cache, _assignee_cache
    _room_cache = None
    _user_cache = None
    _assignee_cache = None
    _reference_date_cache = None


def _get_known_metadata_values(field: str) -> list[str]:
    """ChromaDB 메타데이터에서 고유 값 목록 추출"""
    all_data = chunks_collection.get(include=["metadatas"], limit=10000)
    values = set()
    for meta in all_data["metadatas"]:
        value = meta.get(field, "")
        if value:
            values.add(str(value).strip())
    return sorted(values, key=len, reverse=True)


_assignee_cache: list[str] | None = None


def _get_known_assignees() -> list[str]:
    """ChromaDB에서 실제 담당자 목록을 동적으로 추출 (캐시)"""
    global _assignee_cache
    if _assignee_cache is not None:
        return _assignee_cache

    try:
        _assignee_cache = _get_known_metadata_values("assignee")
        return _assignee_cache
    except Exception:
        return []


def _get_known_rooms() -> list[str]:
    """ChromaDB에서 실제 채팅방 목록을 동적으로 추출 (캐시)"""
    global _room_cache
    if _room_cache is not None:
        return _room_cache

    try:
        _room_cache = _get_known_metadata_values("room")
        return _room_cache
    except Exception:
        return [
            "개발팀", "마케팅팀", "디자인팀", "경영지원팀", "인사팀",
            "프로젝트A", "프로젝트B", "프로젝트C", "신규사업TF", "데이터분석팀",
            "QA팀", "운영팀", "기획팀", "영업팀", "CS팀",
            "동기모임", "점심약속", "스터디그룹", "독서모임", "운동모임",
            "전체공지", "임원회의", "팀장회의", "주간보고", "월간리뷰",
            "백엔드개발", "프론트엔드개발", "인프라팀", "보안팀", "AI연구팀",
        ]


def _get_known_users() -> list[str]:
    """ChromaDB에서 실제 사용자 이름 목록을 동적으로 추출 (캐시)"""
    global _user_cache
    if _user_cache is not None:
        return _user_cache

    try:
        _user_cache = _get_known_metadata_values("user")
        return _user_cache
    except Exception:
        return []


def _get_reference_today() -> date:
    """상대 날짜 해석 기준일

    데이터가 있으면 최신 날짜를 기준으로 삼고, 없으면 시스템 오늘 날짜를 사용한다.
    """
    global _reference_date_cache
    if _reference_date_cache is not None:
        return _reference_date_cache

    try:
        all_data = chunks_collection.get(include=["metadatas"], limit=10000)
        parsed_dates = []
        for meta in all_data["metadatas"]:
            raw_date = meta.get("date")
            if not raw_date:
                continue
            try:
                parsed_dates.append(datetime.strptime(str(raw_date), "%Y-%m-%d").date())
            except ValueError:
                continue
        if parsed_dates:
            _reference_date_cache = max(parsed_dates)
            return _reference_date_cache
    except Exception:
        pass

    _reference_date_cache = datetime.now().date()
    return _reference_date_cache


# === 의도 분류 키워드 ===
_INTENT_KEYWORDS = {
    "list": ["팀원", "이름", "목록", "누구", "사람", "멤버", "참여자", "리스트"],
    "aggregate": ["몇 건", "몇건", "얼마나", "가장 많", "통계", "횟수", "빈도", "카운트", "건수"],
    "summary": ["요약", "정리", "어떤 일", "무슨 일", "무슨 이야기", "어떤 대화", "무엇을 했", "뭘 했", "활동"],
    "search": [],  # 기본값
}


async def analyze_query(query: str) -> QueryAnalysis:
    """규칙 기반 쿼리 분석 (LLM 불필요, <1ms)

    1. 날짜/날짜범위 추출
    2. 채팅방 이름 매칭
    3. 사용자 이름 감지
    4. 의도 분류 (search/summary/list/aggregate)
    5. 검색 전략 결정 (vector/metadata/hybrid/aggregate)
    """
    filters: dict = {}
    clean_query = query  # 필터 추출 후 남은 텍스트 (벡터 검색용)

    # --- 1. 날짜 추출 ---

    # 정확한 날짜: YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", query)
    if m:
        y, mo, d = m.groups()
        filters["date"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        clean_query = clean_query.replace(m.group(0), "")

    # 정확한 날짜: YYYY년 M월 D일
    if "date" not in filters:
        m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", query)
        if m:
            y, mo, d = m.groups()
            filters["date"] = f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
            clean_query = clean_query.replace(m.group(0), "")

    reference_today = _get_reference_today()

    # 월 범위: YYYY년 M월 또는 M월
    if "date" not in filters:
        m = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월", query)
        if m:
            year = int(m.group(1)) if m.group(1) else reference_today.year
            month = int(m.group(2))
            if 1 <= month <= 12:
                filters["date_from"] = f"{year}-{str(month).zfill(2)}-01"
                # 월 마지막 날 계산
                if month == 12:
                    filters["date_to"] = f"{year}-12-31"
                else:
                    next_month = datetime(year, month + 1, 1) - timedelta(days=1)
                    filters["date_to"] = next_month.strftime("%Y-%m-%d")
                clean_query = clean_query.replace(m.group(0), "")

    # 상대 날짜: 오늘, 어제, 이번 주, 최근
    recent_pattern = re.search(r"최근(?:에)?(?:\s*(\d+)\s*(일|주|개월|달))?", query)
    if "이번 주" in query or "이번주" in query:
        week_start = reference_today - timedelta(days=reference_today.weekday())
        filters["date_from"] = week_start.strftime("%Y-%m-%d")
        filters["date_to"] = reference_today.strftime("%Y-%m-%d")
        clean_query = clean_query.replace("이번 주", "")
        clean_query = clean_query.replace("이번주", "")
    elif recent_pattern:
        amount_raw, unit = recent_pattern.groups()
        amount = int(amount_raw) if amount_raw else 7
        if unit == "주":
            days = amount * 7
        elif unit in {"개월", "달"}:
            days = amount * 30
        else:
            days = amount
        filters["date_from"] = (reference_today - timedelta(days=days)).strftime("%Y-%m-%d")
        filters["date_to"] = reference_today.strftime("%Y-%m-%d")
        clean_query = clean_query.replace(recent_pattern.group(0), "")
    elif "오늘" in query:
        filters["date"] = reference_today.strftime("%Y-%m-%d")
        clean_query = clean_query.replace("오늘", "")
    elif "어제" in query:
        filters["date"] = (reference_today - timedelta(days=1)).strftime("%Y-%m-%d")
        clean_query = clean_query.replace("어제", "")

    # --- 2. 담당자 매칭 (이슈 데이터) ---
    known_assignees = _get_known_assignees()
    for assignee in known_assignees:
        assignee_pattern = re.compile(
            rf"(?<![가-힣]){re.escape(assignee)}(?:님|씨|이|가|은|는|을|를|의)?(?:\s*담당)?(?=\s|$)"
        )
        match = assignee_pattern.search(query)
        if match:
            filters["assignee"] = assignee
            clean_query = clean_query.replace(match.group(0), "")
            break

    # --- 2-1. 상태 감지 (이슈 데이터) ---
    _STATUS_MAP = {
        "완료": "완료", "완료된": "완료", "끝난": "완료",
        "진행": "진행", "진행중": "진행", "진행 중": "진행",
        "대기": "대기", "대기중": "대기",
        "미완료": "미완료",
    }
    for keyword, status_val in _STATUS_MAP.items():
        if keyword in query:
            filters["status"] = status_val
            clean_query = clean_query.replace(keyword, "")
            break

    # --- 3. 채팅방 매칭 ---
    known_rooms = _get_known_rooms()
    for room in known_rooms:
        if room in query:
            filters["room"] = room
            clean_query = clean_query.replace(room, "")
            break

    # --- 3. 사용자 이름 감지 ---
    known_users = _get_known_users()
    for user in known_users:
        user_pattern = re.compile(
            rf"(?<![가-힣]){re.escape(user)}(?:님|씨|이|가|은|는|을|를|의)?(?=\s|$)"
        )
        match = user_pattern.search(query)
        if match:
            filters["user"] = user
            clean_query = clean_query.replace(match.group(0), "")
            break

    # --- 4. 의도 분류 ---
    intent = "search"
    for intent_type, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in query:
                intent = intent_type
                break
        if intent != "search":
            break

    # --- 5. 검색 전략 결정 ---
    has_filters = bool(filters)
    has_content_keywords = bool(clean_query.strip())

    if intent == "aggregate":
        strategy = "aggregate"
    elif intent == "list" and has_filters:
        strategy = "aggregate"  # 목록도 집계와 비슷하게 처리
    elif has_filters and has_content_keywords:
        strategy = "hybrid"
    elif has_filters and not has_content_keywords:
        strategy = "metadata"
    else:
        strategy = "vector"

    # 벡터 검색용 텍스트 정리
    search_text = re.sub(r"\s+", " ", clean_query).strip()
    if not search_text:
        search_text = query  # 원본 질의를 폴백으로 사용

    # kiwipiepy 형태소 분석으로 불용어 제거 (조사/어미 제거)
    if settings.use_kiwi_keywords:
        search_text = extract_keywords(search_text)

    analysis = QueryAnalysis({
        "intent": intent,
        "filters": filters,
        "search_text": search_text,
        "strategy": strategy,
    })

    print(f"[쿼리분석] {analysis}")
    return analysis
