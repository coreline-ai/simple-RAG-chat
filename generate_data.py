"""1만건 랜덤 채팅 데이터 생성 스크립트"""
import random
import datetime
import os

# 채팅방 이름 풀
rooms = [
    "개발팀", "마케팅팀", "디자인팀", "경영지원팀", "인사팀",
    "프로젝트A", "프로젝트B", "프로젝트C", "신규사업TF", "데이터분석팀",
    "QA팀", "운영팀", "기획팀", "영업팀", "CS팀",
    "동기모임", "점심약속", "스터디그룹", "독서모임", "운동모임",
    "전체공지", "임원회의", "팀장회의", "주간보고", "월간리뷰",
    "백엔드개발", "프론트엔드개발", "인프라팀", "보안팀", "AI연구팀",
]

# 사용자 이름 풀
first_names = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임",
               "한", "오", "서", "신", "권", "황", "안", "송", "류", "홍"]
last_names = ["민수", "지영", "서준", "하은", "도윤", "수아", "예준", "지우",
              "시우", "하윤", "준서", "서연", "현우", "민서", "지호", "윤서",
              "은우", "채원", "승현", "소율", "태영", "다은", "재민", "유진",
              "성호", "미래", "정훈", "수진", "동현", "혜진"]

# 입력내용 템플릿
templates = [
    "오늘 회의 {}시에 시작합니다",
    "{}건 보고서 검토 부탁드립니다",
    "서버 배포 {}차 완료했습니다",
    "이번 주 {}요일까지 제출해주세요",
    "{}페이지 문서 초안 공유합니다",
    "API 응답 속도가 {}ms로 개선됐어요",
    "테스트 커버리지 {}% 달성했습니다",
    "고객사 미팅 {}분 전입니다",
    "점심 메뉴 {}으로 할까요?",
    "코드 리뷰 {}건 남아있습니다",
    "이슈 #{} 해결했습니다",
    "릴리즈 v{}.0 준비 중입니다",
    "DB 마이그레이션 {}단계 진행 중",
    "{}분 후에 스탠드업 미팅 시작합니다",
    "이번 스프린트 목표 {}건 완료",
    "디자인 시안 {}번째 버전 올렸습니다",
    "사용자 피드백 {}건 정리했어요",
    "배치 작업 {}% 완료되었습니다",
    "메모리 사용량이 {}GB입니다",
    "장애 대응 {}차 완료, 모니터링 중",
    "신규 기능 {}개 기획안 검토해주세요",
    "보안 점검 결과 취약점 {}건 발견",
    "이번 달 매출 목표 {}% 달성",
    "교육 자료 {}장 슬라이드 준비 완료",
    "CI/CD 파이프라인 {}단계 추가했습니다",
    "네트워크 지연 {}ms로 확인됩니다",
    "PR #{} 머지 부탁드립니다",
    "온보딩 문서 {}페이지 업데이트 완료",
    "로그 분석 결과 에러율 {}% 입니다",
    "캐시 적중률 {}%로 안정적입니다",
    "안녕하세요, {} 관련 문의드립니다",
    "감사합니다, {}건 처리 완료했습니다",
    "다음 주 {}요일 휴가 신청합니다",
    "{}님 혹시 시간 되시나요?",
    "공유드린 문서 {}페이지 확인 부탁드립니다",
    "오류 로그 확인해보니 {}번 라인이 문제입니다",
    "성능 테스트 결과 TPS {}으로 측정됐습니다",
    "Docker 이미지 {}MB로 최적화했습니다",
    "SSL 인증서 {}일 후 만료 예정입니다",
    "백업 완료, 총 {}GB 저장됨",
]

lunch_menus = ["김치찌개", "된장찌개", "비빔밥", "불고기", "삼겹살",
               "치킨", "피자", "햄버거", "초밥", "라멘", "짜장면",
               "짬뽕", "떡볶이", "김밥", "냉면", "칼국수", "샐러드",
               "샌드위치", "파스타", "스테이크"]

days = ["월", "화", "수", "목", "금"]

filler_messages = [
    "네 알겠습니다",
    "확인했습니다 감사합니다",
    "수고하셨습니다!",
    "좋은 아침이에요",
    "회의록 공유 부탁드려요",
    "다들 고생 많으셨습니다",
    "오후에 다시 연락드리겠습니다",
    "링크 공유해주실 수 있나요?",
    "진행 상황 업데이트 부탁드립니다",
    "잠시 후 답변 드리겠습니다",
    "일정 조율 필요합니다",
    "지금 가능하신가요?",
    "메일로도 공유 부탁드립니다",
    "내일까지 확인해보겠습니다",
    "다음 주에 논의하면 좋겠습니다",
    "화면 공유 부탁드립니다",
    "좋은 의견이네요 반영하겠습니다",
    "테스트 환경에서 확인해볼게요",
    "운영 서버 반영은 내일 예정입니다",
    "이 부분 좀 더 논의가 필요할 것 같아요",
    "문서 업데이트하고 공유하겠습니다",
    "이전 버전으로 롤백했습니다",
    "모니터링 대시보드 확인해주세요",
    "슬랙 채널 확인 부탁드립니다",
    "지라 티켓 생성했습니다",
    "컨플루언스에 정리해두었습니다",
    "깃헙 이슈 등록 완료했습니다",
    "노션 페이지 업데이트 했습니다",
    "재택근무 중입니다",
    "외근 중이라 늦을 수 있습니다",
]

def generate_content():
    """랜덤 메시지 내용 생성"""
    if random.random() < 0.4:
        return random.choice(filler_messages)

    template = random.choice(templates)
    if "{}요일" in template:
        return template.format(random.choice(days))
    elif "{}으로 할까요" in template:
        return template.format(random.choice(lunch_menus))
    elif "{}님" in template:
        name = random.choice(first_names) + random.choice(last_names)
        return template.format(name)
    else:
        num = random.randint(1, 500)
        return template.format(num)

def generate_user():
    """랜덤 사용자 이름 생성"""
    return random.choice(first_names) + random.choice(last_names)

def generate_data(count=10000):
    """채팅 데이터 생성"""
    lines = []
    # 2024-01-01 ~ 2026-03-24 범위
    start_date = datetime.datetime(2024, 1, 1)
    end_date = datetime.datetime(2026, 3, 24)
    delta = (end_date - start_date).total_seconds()

    users_pool = list(set(generate_user() for _ in range(200)))

    for i in range(count):
        # 랜덤 날짜/시간
        random_seconds = random.uniform(0, delta)
        dt = start_date + datetime.timedelta(seconds=random_seconds)
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H:%M:%S")

        room = random.choice(rooms)
        content = generate_content()
        user = random.choice(users_pool)

        line = f"[{date_str}, {time_str}, {room}, {content}, {user}]"
        lines.append(line)

    # 시간순 정렬
    lines.sort()
    return lines

if __name__ == "__main__":
    random.seed(42)
    data = generate_data(10000)

    output_path = os.path.join(os.path.dirname(__file__), "data", "chat_logs.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(data))

    print(f"생성 완료: {len(data)}건 -> {output_path}")
