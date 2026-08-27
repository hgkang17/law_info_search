"""인용 문구가 실제 조문 본문과 맞는지 본다.

존재 확인만으로는 '있는 조문에 엉뚱한 내용을 붙인' 답을 못 잡는다.
정규화 후 긴 공통 부분 문자열, 이어서 문자 bigram Jaccard로 판정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from utils.patterns import CIRCLED_NUMBER_MARKERS

MIN_EXACT_LEN = 30
JACCARD_THRESHOLD = 0.25
_CIRCLED_INDEX = {marker: index + 1 for index, marker in enumerate(CIRCLED_NUMBER_MARKERS)}


@dataclass(frozen=True)
class ContentMatchResult:
    matched: bool
    method: str
    score: float
    claim_len: int
    actual_len: int


def normalize_legal_text(value: str) -> str:
    cleaned: list[str] = []
    for char in str(value or ""):
        code = ord(char)
        if code in (0x200B, 0x200C, 0x200D, 0xFEFF):
            continue
        cleaned.append(" " if code == 0x00A0 else char)
    text = "".join(cleaned)
    text = "".join(
        f"({_CIRCLED_INDEX[ch]})" if ch in _CIRCLED_INDEX else ch for ch in text
    )
    text = text.replace("「", "").replace("『", "").replace("」", "").replace("』", "")
    text = text.replace("·", " ").replace("•", " ")
    return " ".join(text.split())


def _bigrams(value: str) -> set[str]:
    compact = "".join(
        ch
        for ch in normalize_legal_text(value).casefold()
        if ch.isalnum() or ("가" <= ch <= "힣")
    )
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[index : index + 2] for index in range(len(compact) - 1)}


def _longest_common_substring_len(left: str, right: str) -> int:
    if not left or not right:
        return 0
    previous = [0] * (len(right) + 1)
    best = 0
    for left_ch in left:
        current = [0] * (len(right) + 1)
        for column, right_ch in enumerate(right, start=1):
            if left_ch == right_ch:
                current[column] = previous[column - 1] + 1
                if current[column] > best:
                    best = current[column]
        previous = current
    return best


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    inter = len(left & right)
    union = len(left) + len(right) - inter
    return 0.0 if union == 0 else inter / union


def match_citation_content(claim: str, actual: str) -> ContentMatchResult:
    normalized_claim = normalize_legal_text(claim)
    normalized_actual = normalize_legal_text(actual)
    claim_len = len(normalized_claim)
    actual_len = len(normalized_actual)
    if not normalized_claim or not normalized_actual:
        return ContentMatchResult(False, "mismatch", 0.0, claim_len, actual_len)
    if claim_len < MIN_EXACT_LEN and normalized_claim in normalized_actual:
        return ContentMatchResult(True, "exact", 1.0, claim_len, actual_len)
    common = _longest_common_substring_len(normalized_claim, normalized_actual)
    if common >= MIN_EXACT_LEN:
        return ContentMatchResult(True, "exact", 1.0, claim_len, actual_len)
    score = _jaccard(_bigrams(normalized_claim), _bigrams(normalized_actual))
    if score >= JACCARD_THRESHOLD:
        return ContentMatchResult(True, "token-jaccard", score, claim_len, actual_len)
    return ContentMatchResult(False, "mismatch", score, claim_len, actual_len)
