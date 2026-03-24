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
"""
import re
from datetime import datetime, timedelta

from app.config import settings
from app.database import chunks_collection


class QueryAnalysis:
    """쿼리 분석 결과"""

    def __init__(self, raw: dict):
        self.intent = raw.get("intent", "search")
        self.filters = raw.get("filters", {})
        self.search_text = raw.get("search_text", "")
        self.strategy = raw.get("strategy", "hybrid")

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

    def __repr__(self):
        return (
            f"QueryAnalysis(intent={self.intent}, strategy={self.strategy}, "
            f"room={self.room}, user={self.user}, date={self.date}, "
            f"date_from={self.date_from}, date_to={self.date_to}, "
            f"search_text='{self.search_text}')"
        )


# === 채팅방 목록 (DB에서 동적 조회 + 캐시) ===
_room_cache: list[str] | None = None


def _get_known_rooms() -> list[str]:
    """ChromaDB에서 실제 채팅방 목록을 동적으로 추출 (캐시)"""
    global _room_cache
    if _room_cache is not None:
        return _room_cache

    try:
        all_data = chunks_collection.get(include=["metadatas"], limit=10000)
        rooms = set()
        for meta in all_data["metadatas"]:
            room = meta.get("room", "")
            if room:
                rooms.add(room)
        _room_cache = sorted(rooms, key=len, reverse=True)  # 긴 이름 우선 매칭
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


# === 사용자 이름 패턴 ===
# 한국어 이름: 성(1자) + 이름(2자) = 3자
# 뒤에 조사(이/가/의/는/을/를/에게/한테)가 오거나 공백/문장끝이어야 함
_NAME_PATTERN = re.compile(
    r"(김|이|박|최|정|강|조|윤|장|임|한|오|서|신|권|황|안|송|류|홍)"
    r"[가-힣]{2}"
    r"(?=이|가|의|는|을|를|에게|한테|님|\s|$)"
)


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

    # 월 범위: YYYY년 M월 또는 M월
    if "date" not in filters:
        m = re.search(r"(?:(\d{4})년\s*)?(\d{1,2})월", query)
        if m:
            year = int(m.group(1)) if m.group(1) else 2024
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
    today = datetime(2026, 3, 24)  # 데이터 기준일
    if "최근" in query or "이번 주" in query:
        filters["date_from"] = (today - timedelta(days=7)).strftime("%Y-%m-%d")
        filters["date_to"] = today.strftime("%Y-%m-%d")
    elif "오늘" in query:
        filters["date"] = today.strftime("%Y-%m-%d")
    elif "어제" in query:
        filters["date"] = (today - timedelta(days=1)).strftime("%Y-%m-%d")

    # --- 2. 채팅방 매칭 ---
    known_rooms = _get_known_rooms()
    for room in known_rooms:
        if room in query:
            filters["room"] = room
            clean_query = clean_query.replace(room, "")
            break

    # --- 3. 사용자 이름 감지 ---
    # "이름을", "이번에", "이런" 등 일반 단어를 제외
    _NOT_NAMES = {
        "이름을", "이름이", "이름은", "이름의", "이름",
        "이번에", "이번은", "이번의", "이번",
        "이런게", "이런걸", "이런식", "이런",
        "이전에", "이전의", "이전", "이후에", "이후의", "이후",
        "이상이", "이상의", "이상은", "이상",
        "이하의", "이하", "이유는", "이유를", "이유",
        "이것은", "이것이", "이것", "이미",
        "임원회", "임원회의",
    }
    name_match = _NAME_PATTERN.search(query)
    if name_match:
        name = name_match.group(0)
        # 원본 텍스트에서 매칭된 위치의 전체 단어 확인
        start = name_match.start()
        end = name_match.end()
        # 뒤에 1글자까지 포함하여 일반 단어인지 확인
        extended = query[start:min(end + 1, len(query))]
        if name not in _NOT_NAMES and extended not in _NOT_NAMES:
            filters["user"] = name
            clean_query = clean_query.replace(name, "")

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

    analysis = QueryAnalysis({
        "intent": intent,
        "filters": filters,
        "search_text": search_text,
        "strategy": strategy,
    })

    print(f"[쿼리분석] {analysis}")
    return analysis
