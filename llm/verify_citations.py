"""AI 답에 적힌 조문 인용이 법제처에 실존하는지 확인한다.

화면의 조항호목 팝업과 같은 API(eflawjosub)로 그 조만 읽는다.
조 하나 확인하려고 법령 전문을 받지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from urllib.parse import quote

import molit_cgm_expc_api as api
from llm.document_labels import lookup_cached_document_label
from utils.annex_notation import annex_related_law_name
from utils.citation_match import match_citation_content
from utils.parsing import extract_law_article, normalize_article_jo
from utils.patterns import LAW_UNIT_REFERENCE_PATTERN

_CITATION_PATTERN = re.compile(r"\[([^\]]+)\]\((law|doc):([^:)]+):([^)]+)\)")
_ARTICLE_MENTION = re.compile(r"제\s*\d+\s*조(?:\s*의\s*\d+)?")

STATUS_VERIFIED = "verified"
STATUS_MISSING = "missing"
STATUS_UNCHECKED = "unchecked"
STATUS_MISMATCH = "mismatch"

_CLAIM_QUOTE = re.compile(r"[「\"“']([^」\"”']{8,400})[」\"”']")


# 법령·행정규칙 제목으로 끝나는지. 긴 접미사부터 본다.
_LAW_TITLE_SUFFIX = re.compile(
    r"(?:법률|시행령|시행규칙|조례|지침|고시|훈령|예규|규정|규칙|법)$"
)


def _quote_law_title(name: str) -> str:
    title = name.strip().strip("「」")
    return f"「{title}」" if title else name


def display_citation_label(label: str) -> str:
    """법령명만 낫표로 감싸되 뒤의 조항호목은 링크 라벨에 남긴다."""
    text = str(label or "").strip()
    if not text or text.startswith("「"):
        return text
    match = re.match(r"^(.+?)\s+(제\s*\d+\s*조.*)$", text)
    if match is not None:
        name = match.group(1).strip().strip("「」")
        unit = match.group(2).strip()
        return f"{_quote_law_title(name)} {unit}" if name else text
    suffix = _LAW_TITLE_SUFFIX.search(text)
    # "법", "지침" 단독은 제목이 아니다. 앞에 이름이 있어야 낫표를 붙인다.
    if suffix is not None and suffix.start() > 0:
        return _quote_law_title(text)
    return text


@dataclass(frozen=True)
class CitationCheck:
    """한 인용에 대한 실존 확인 결과."""

    label: str
    status: str
    href: str = ""
    detail: str = ""
    law_id: str = ""
    jo: str = ""
    claim: str = ""


def citation_annexref(
    label: str,
    *,
    category: str = "licbyl",
    item_id: str = "",
    related: str = "",
) -> str:
    """별표·서식 인용은 조문 팝업이 아니라 별표 원문으로 연다."""
    parameters = [f"name={quote(str(label or '').strip(), safe='')}"]
    if category:
        parameters.append(f"category={quote(category, safe='')}")
    if item_id:
        parameters.append(f"id={quote(item_id, safe='')}")
    related_name = str(related or "").strip() or annex_related_law_name(label)
    if related_name:
        parameters.append(f"related={quote(related_name, safe='')}")
    return f"annexref://open?{'&'.join(parameters)}"


def citation_lawref(label: str, law_id: str, jo: str) -> str:
    """본문 화면과 같은 lawref:// 조항호목 주소를 만든다."""
    if _ANNEX_NAME.search(str(label or "")):
        return citation_annexref(label)
    name = re.sub(r"\s*제\d+조.*$", "", label).strip() or label
    unit = LAW_UNIT_REFERENCE_PATTERN.search(label)
    jo_number = (unit.group("jo") if unit else "") or ""
    jo_branch = (unit.group("jo_branch") if unit else "") or ""
    hang = (unit.group("hang") if unit else "") or ""
    hang_branch = (unit.group("hang_branch") if unit else "") or ""
    ho = (unit.group("ho") if unit else "") or ""
    ho_branch = (unit.group("ho_branch") if unit else "") or ""
    mok = (unit.group("mok") if unit else "") or ""
    if not jo_number and jo:
        try:
            code = normalize_article_jo(jo)
            jo_number = str(int(code[:4]))
            branch = int(code[4:])
            if branch and not jo_branch:
                jo_branch = str(branch)
        except ValueError:
            jo_number = str(jo).lstrip("0") or str(jo)
    parameters = []
    if name:
        parameters.append(f"name={quote(name, safe='')}")
    if law_id:
        parameters.append(f"id={quote(str(law_id), safe='')}")
    if jo_number:
        parameters.append(f"jo={quote(jo_number, safe='')}")
    if jo_branch:
        parameters.append(f"jo_branch={quote(jo_branch, safe='')}")
    if hang:
        parameters.append(f"hang={quote(hang, safe='')}")
    if hang_branch:
        parameters.append(f"hang_branch={quote(hang_branch, safe='')}")
    if ho:
        parameters.append(f"ho={quote(ho, safe='')}")
    if ho_branch:
        parameters.append(f"ho_branch={quote(ho_branch, safe='')}")
    if mok:
        parameters.append(f"mok={quote(mok, safe='')}")
    return f"lawref://open?{'&'.join(parameters)}"


_LAW_NAME_QUOTED = re.compile(r"「([^」]+)」")
# 별표·서식 이름은 법령명이 아니다. 조문을 여기에 붙이면 안 된다.
_ANNEX_NAME = re.compile(r"별표|별지|서식|양식")


def _article_key(label: str) -> tuple[str, str]:
    """법령명과 조 번호만 남겨, 같은 조문인지 견주는 열쇠로 쓴다."""
    text = str(label or "")
    unit = LAW_UNIT_REFERENCE_PATTERN.search(text)
    jo = (unit.group("jo") if unit else "") or ""
    branch = (unit.group("jo_branch") if unit else "") or ""
    name = re.sub(r"\s*제\s*\d+\s*조.*$", "", text)
    name = re.sub(r"\s+", "", name).strip("「」")
    return name, f"{jo}-{branch}" if branch else jo


def _law_before(source: str, position: int) -> tuple[str, str]:
    """그 자리 바로 앞에서 마지막으로 나온 법령명과 ID를 집는다.

    답 본문은 「국토계획법 시행령」 제21조 · 제21조처럼 가운데 점으로
    조문을 잇는다. 뒤쪽 조문에는 법령명이 없어 그대로 두면 링크가 걸리지
    않는다. 본문 링크와 같은 규칙으로 앞의 법령을 물려받는다.
    """
    best_at = -1
    name = ""
    law_id = ""
    for match in _CITATION_PATTERN.finditer(source):
        if match.start() >= position or match.group(2) != "law":
            continue
        candidate = re.sub(r"\s*제\s*\d+\s*조.*$", "", match.group(1))
        candidate = candidate.strip().strip("「」")
        if candidate and not _ANNEX_NAME.search(candidate) and match.start() > best_at:
            best_at = match.start()
            name = candidate
            law_id = match.group(3)
    for match in _LAW_NAME_QUOTED.finditer(source):
        if match.start() >= position:
            break
        candidate = match.group(1).strip()
        if candidate and not _ANNEX_NAME.search(candidate) and match.start() > best_at:
            best_at = match.start()
            name = candidate
            law_id = ""
    return name, law_id


def collect_citations(text: str) -> list[CitationCheck]:
    """링크된 조문과, 링크 없이 남은 제N조를 가린다."""
    source = str(text or "")
    covered: list[tuple[int, int]] = []
    checks: list[CitationCheck] = []
    seen: set[tuple[str, str, str]] = set()
    for match in _CITATION_PATTERN.finditer(source):
        covered.append(match.span())
        if match.group(2) != "law":
            continue
        label = match.group(1)
        law_id = match.group(3)
        jo = match.group(4)
        nearby = source[match.end() : match.end() + 240]
        quoted = _CLAIM_QUOTE.search(nearby)
        key = (law_id, jo, label)
        if key in seen:
            continue
        seen.add(key)
        if _ANNEX_NAME.search(label):
            related = annex_related_law_name(label)
            if not related:
                related, _ = _law_before(source, match.start())
            if not related:
                related = lookup_cached_document_label(law_id)
            checks.append(
                CitationCheck(
                    label=label,
                    status=STATUS_UNCHECKED,
                    href=citation_annexref(label, related=related),
                    claim=quoted.group(1) if quoted else "",
                )
            )
            continue
        checks.append(
            CitationCheck(
                label=label,
                status=STATUS_UNCHECKED,
                href=citation_lawref(label, law_id, jo),
                law_id=law_id,
                jo=jo,
                claim=quoted.group(1) if quoted else "",
            )
        )
    linked_articles = {_article_key(item.label) for item in checks}
    for match in _ARTICLE_MENTION.finditer(source):
        start, end = match.span()
        if any(left <= start < right for left, right in covered):
            continue
        mention = re.sub(r"\s+", "", match.group(0))
        name, law_id = _law_before(source, start)
        label = f"{name} {mention}" if name else mention
        if _article_key(label) in linked_articles:
            # 앞에서 이미 링크로 적은 그 조문이다. 한 줄에 두 번 적지 않는다.
            continue
        key = ("", label, "")
        if key in seen:
            continue
        seen.add(key)
        checks.append(
            CitationCheck(
                label=label,
                status=STATUS_UNCHECKED,
                # 물려받은 법령은 추측이므로 실존 판정까지 하지는 않는다.
                # 열어 볼 수 있게 링크만 걸고 미확인으로 남긴다.
                href=citation_lawref(label, law_id, "") if name else "",
                detail=(
                    "앞에 나온 법령으로 이어 붙인 조문 언급"
                    if name
                    else "링크로 확인되지 않은 조문 언급"
                ),
            )
        )
    return checks


def _hang_ho_from_label(label: str) -> tuple[str, str]:
    unit = LAW_UNIT_REFERENCE_PATTERN.search(label)
    if unit is None:
        return "", ""
    return str(unit.group("hang") or ""), str(unit.group("ho") or "")


def _article_text(oc_key: str, law_id: str, jo: str, label: str, *, fetch) -> str:
    try:
        jo_code = normalize_article_jo(jo)
    except ValueError:
        return ""
    hang, ho = _hang_ho_from_label(label)
    data = fetch(oc_key, law_id, jo_code, hang=hang, ho=ho)
    text = extract_law_article(data, jo_code, hang, ho)
    if text:
        return text
    if isinstance(data, dict):
        law = data.get("법령", data)
        if isinstance(law, dict):
            units = law.get("조문", {})
            units = units.get("조문단위") if isinstance(units, dict) else units
            if units:
                from utils.parsing import law_article_text

                return law_article_text(units)
    return ""


def verify_answer_citations(
    oc_key: str,
    text: str,
    *,
    fetch=None,
) -> list[CitationCheck]:
    """답 본문의 조문 링크를 조항호목 API로 확인한다.

    fetch를 바꾸어 끼우면 실제 법제처를 부르지 않고 시험할 수 있다.
    링크가 없는 제N조는 법령을 추측하지 않고 미확인으로 남긴다.
    """
    reader = fetch if fetch is not None else api.get_law_article
    results: list[CitationCheck] = []
    for item in collect_citations(text):
        if _ANNEX_NAME.search(item.label):
            results.append(item)
            continue
        if not item.law_id or not item.jo:
            results.append(item)
            continue
        try:
            article_text = _article_text(
                oc_key, item.law_id, item.jo, item.label, fetch=reader
            )
        except Exception as error:  # noqa: BLE001 - 검증 실패가 답을 지우면 안 된다.
            results.append(
                CitationCheck(
                    label=item.label,
                    status=STATUS_UNCHECKED,
                    href=item.href,
                    detail=f"확인 실패: {error}",
                    law_id=item.law_id,
                    jo=item.jo,
                    claim=item.claim,
                )
            )
            continue
        if not article_text:
            status = STATUS_MISSING
            detail = "해당 조문 없음"
        elif item.claim and not match_citation_content(item.claim, article_text).matched:
            status = STATUS_MISMATCH
            detail = "조문은 있으나 인용 내용이 본문과 다름"
        else:
            status = STATUS_VERIFIED
            detail = "실존"
        results.append(
            CitationCheck(
                label=item.label,
                status=status,
                href=item.href,
                detail=detail,
                law_id=item.law_id,
                jo=item.jo,
                claim=item.claim,
            )
        )
    return results


def verification_html(checks: list[CitationCheck]) -> str:
    """답에서 사용한 조문을 링크 가능 여부만 유지해 한 줄로 모은다."""
    if not checks:
        return ""
    items: list[str] = []
    for item in checks:
        shown = display_citation_label(item.label)
        if item.href:
            items.append(
                f'<a href="{escape(item.href, quote=True)}">'
                f"{escape(shown)}</a>"
            )
        else:
            items.append(escape(shown))
    return "<b>사용한 법령 조문</b><br>" + " · ".join(items)


