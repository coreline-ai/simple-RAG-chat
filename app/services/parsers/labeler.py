"""행동 흐름 라벨링 — KSS + 규칙 기반

문제점 분석 텍스트를 문장 단위로 분리한 후,
규칙 기반으로 행동 라벨(discovery/attempt/fix/result 등)을 부여하고,
인접 라벨을 묶어 의미 있는 행동 흐름 chunk로 조합한다.

흐름:
  1단계: KSS 문장 분리
  2단계: 규칙 기반 라벨링 (형태소 분석 + 정규식)
  3단계: 인접 라벨 묶기 (행동 흐름 chunk)
"""
from __future__ import annotations

import re
from typing import Any


# === 라벨 정의 + 규칙 ===

LABEL_RULES: list[tuple[str, list[str]]] = [
    ("discovery", [
        r"확인", r"발견", r"로그", r"보니", r"파악", r"조사",
        r"분석", r"살펴", r"검토", r"나타나", r"드러나",
    ]),
    ("attempt", [
        r"시도", r"추가", r"적용", r"변경", r"설정",
        r"조정", r"도입", r"구현", r"작성",
    ]),
    ("failure", [
        r"실패", r"해결되지", r"동일", r"재발", r"지속",
        r"안 됨", r"불가", r"재현", r"여전히", r"못 ",
    ]),
    ("fix", [
        r"수정", r"제거", r"교체", r"반영", r"개선",
        r"패치", r"업데이트", r"롤백", r"복구",
    ]),
    ("result", [
        r"정상", r"해결", r"복구", r"개선", r"안정",
        r"감소", r"증가.*성능", r"효과", r"완료",
    ]),
    ("verification", [
        r"재현 테스트", r"검증", r"테스트 완료", r"확인 완료",
        r"모니터링", r"관찰", r"추적",
    ]),
    ("next_action", [
        r"예정", r"추후", r"추가.*필요", r"향후", r"계획",
        r"해야", r"필요합니다", r"권장",
    ]),
]

# 라벨 묶기 규칙: 인접한 라벨이 이 조합이면 하나의 흐름으로 합침
FLOW_MERGE_RULES: list[set[str]] = [
    {"discovery"},                      # 발견 단독
    {"attempt", "failure"},             # 시도 → 실패
    {"fix", "result"},                  # 수정 → 결과
    {"verification"},                   # 검증 단독
    {"next_action"},                    # 후속 조치 단독
    {"attempt", "fix"},                 # 시도 → 수정
    {"result", "verification"},         # 결과 → 검증
]

# 라벨별 흐름 이름
FLOW_NAMES = {
    frozenset({"discovery"}): "원인 발견",
    frozenset({"attempt", "failure"}): "시도 및 실패",
    frozenset({"fix", "result"}): "수정 및 결과",
    frozenset({"attempt", "fix"}): "시도 및 수정",
    frozenset({"result", "verification"}): "결과 검증",
    frozenset({"verification"}): "검증",
    frozenset({"next_action"}): "후속 조치",
}


def label_sentence(sentence: str) -> str:
    """규칙 기반 문장 라벨링"""
    for label, patterns in LABEL_RULES:
        if any(re.search(p, sentence) for p in patterns):
            return label
    return "other"


def split_and_label(text: str) -> list[dict]:
    """텍스트를 문장 분리 + 라벨링

    Returns:
        [{"text": str, "label": str}, ...]
    """
    if not text or not text.strip():
        return []

    try:
        from kss import split_sentences
        sentences = split_sentences(text.strip(), backend="pecab")
    except Exception:
        # KSS 실패 시 마침표 기준 단순 분리
        sentences = [s.strip() for s in re.split(r'(?<=[.!?])\s+', text.strip()) if s.strip()]

    if not sentences:
        return [{"text": text.strip(), "label": "other"}]

    return [{"text": s, "label": label_sentence(s)} for s in sentences]


def build_flow_chunks(labeled_sentences: list[dict]) -> list[dict]:
    """인접 라벨을 묶어 행동 흐름 chunk 생성

    같은 라벨 또는 자연스러운 라벨 전이(attempt→failure, fix→result)를
    하나의 chunk로 묶는다.

    Returns:
        [{"text": str, "labels": list[str], "flow_name": str}, ...]
    """
    if not labeled_sentences:
        return []

    chunks: list[dict] = []
    current_texts: list[str] = [labeled_sentences[0]["text"]]
    current_labels: list[str] = [labeled_sentences[0]["label"]]

    for item in labeled_sentences[1:]:
        label = item["label"]
        prev_label = current_labels[-1]

        # 같은 라벨이면 합침
        if label == prev_label:
            current_texts.append(item["text"])
            current_labels.append(label)
            continue

        # 자연스러운 전이인지 확인
        label_set = set(current_labels + [label])
        if _is_natural_flow(label_set):
            current_texts.append(item["text"])
            current_labels.append(label)
            continue

        # 새 chunk 시작
        chunks.append(_make_chunk(current_texts, current_labels))
        current_texts = [item["text"]]
        current_labels = [label]

    # 마지막 chunk
    chunks.append(_make_chunk(current_texts, current_labels))

    return chunks


def _is_natural_flow(label_set: set[str]) -> bool:
    """라벨 조합이 자연스러운 흐름인지 확인"""
    # other는 항상 독립
    if "other" in label_set:
        return False

    clean = label_set - {"other"}
    for rule in FLOW_MERGE_RULES:
        if clean.issubset(rule):
            return True
    return False


def _make_chunk(texts: list[str], labels: list[str]) -> dict:
    """chunk 딕셔너리 생성"""
    unique_labels = list(dict.fromkeys(labels))  # 순서 유지 중복 제거
    label_set = frozenset(set(unique_labels) - {"other"})

    flow_name = FLOW_NAMES.get(label_set, "+".join(unique_labels))

    return {
        "text": " ".join(texts),
        "labels": unique_labels,
        "flow_name": flow_name,
    }
