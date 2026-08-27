"""조문 경계 앵커. '제103조'와 '제1032조'를 가른다."""

from __future__ import annotations

import re

from llm.law_aliases import compact_law_key, resolve_law_alias
from utils.parsing import article_jo_label, normalize_article_jo

LAW_NAME_SUFFIX_PATTERN = r"(?:법률|법|시행령|시행규칙|규칙|규정|조례)"
_ARTICLE_REF_RE = re.compile(
    rf"((?:[가-힣]{{1,28}})?{LAW_NAME_SUFFIX_PATTERN})?\s*[」』】〕]?\s*"
    r"제\s*(\d+)\s*조(?:\s*(?:의|-)\s*(\d+))?"
)
_ARTICLE_RANGE_RE = re.compile(
    r"제\s*(\d+)\s*조(?:\s*(?:의|-)\s*\d+)?\s*(?:부터|~|∼|-)\s*"
    r"제\s*(\d+)\s*조(?:\s*(?:의|-)\s*\d+)?(?:\s*까지)?"
)
_INSTRUMENT_RE = re.compile(r"(시행규칙|시행령|규칙|규정|조례)$")
_OLD_LAW_PREFIX_RE = re.compile(r"(?:^|[^가-힣])[구舊]\s*[「『【〔]?\s*$")
_CITED_LAW_RE = re.compile(rf"「([^」]{{1,39}}?{LAW_NAME_SUFFIX_PATTERN})」")


def parse_article_anchor(raw: str, law_name: str = "") -> dict | None:
    """자연어 조 표기나 6자리 코드를 앵커로 바꾼다. 해석 불가면 None."""
    try:
        code = normalize_article_jo(raw)
    except ValueError:
        return None
    if len(code) != 6:
        return None
    article_no = int(code[:4])
    branch_no = int(code[4:])
    if article_no <= 0:
        return None
    return {
        "code": code,
        "display": article_jo_label(code),
        "article_no": article_no,
        "branch_no": branch_no,
        "law_name": str(law_name or "").strip(),
    }


def _is_contraction_of(short: str, long: str) -> bool:
    index = 0
    for char in long:
        if index < len(short) and char == short[index]:
            index += 1
    return index == len(short)


def _instrument(name_key: str) -> str:
    match = _INSTRUMENT_RE.search(name_key)
    return match.group(1) if match else ""


def classify_law_name(candidate: str, target: str) -> str:
    """same / different / unknown. 확정적으로 다를 때만 different."""
    candidate_key = compact_law_key(resolve_law_alias(candidate).canonical)
    target_key = compact_law_key(resolve_law_alias(target).canonical)
    if not candidate_key or not target_key:
        return "unknown"
    if candidate_key == target_key:
        return "same"
    if _instrument(candidate_key) != _instrument(target_key):
        return "different"
    if len(candidate_key) >= len(target_key):
        return "different"
    return "unknown" if _is_contraction_of(candidate_key, target_key) else "different"


def classify_article_refs(text: str, anchor: dict) -> str:
    """match / hold / mismatch / law-mismatch / silent."""
    folded = (
        str(text or "")
        .replace("第", "제")
        .replace("條", "조")
        .replace("之", "의")
    )
    article_no = int(anchor["article_no"])
    for match in _ARTICLE_RANGE_RE.finditer(folded):
        start = int(match.group(1))
        end = int(match.group(2))
        if start <= article_no <= end:
            return "match"
    saw_ref = False
    held = False
    law_mismatch = False
    law_name = str(anchor.get("law_name") or "")
    for match in _ARTICLE_REF_RE.finditer(folded):
        saw_ref = True
        found_article = int(match.group(2))
        found_branch = int(match.group(3) or 0)
        if found_article != article_no or found_branch != int(anchor["branch_no"]):
            continue
        if not law_name:
            return "match"
        cited = match.group(1) or ""
        verdict = classify_law_name(cited, law_name) if cited else "unknown"
        if verdict == "same":
            return "match"
        if verdict == "unknown" or _OLD_LAW_PREFIX_RE.search(folded[: match.start()]):
            held = True
        else:
            law_mismatch = True
    if held:
        return "hold"
    if law_mismatch:
        return "law-mismatch"
    return "mismatch" if saw_ref else "silent"


def extract_cited_laws(article_text: str, limit: int = 10) -> list[str]:
    """조문 본문의 「」 인용 법령명."""
    found: list[str] = []
    seen: set[str] = set()
    for match in _CITED_LAW_RE.finditer(article_text or ""):
        name = match.group(1).strip()
        key = compact_law_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        found.append(name)
        if len(found) >= limit:
            break
    return found
