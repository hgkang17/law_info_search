"""조문 한 줄이 판례·해석례·헌재·행심·조례에 인용된 영향을 모은다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

import molit_cgm_expc_api as api
from llm.article_anchor import (
    classify_article_refs,
    extract_cited_laws,
    parse_article_anchor,
)
from llm.case_sources import CASE_SOURCES
from llm.law_aliases import resolved_law_matches, score_law_relevance
from models.law import RESOURCE_CATEGORIES
from utils.parsing import extract_law_article, json_text

_NOT_FOUND = "[NOT_FOUND]"
_BUCKETS = (
    ("prec", "대법원 판례", 5),
    ("detc", "헌재 결정례", 3),
    ("expc", "법령해석례", 5),
    ("decc", "행정심판례", 3),
)


def _as_list(value: object) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _law_rows(data: dict, query: str) -> list:
    meta = RESOURCE_CATEGORIES["law"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    rows = [
        row
        for row in _as_list(block.get(meta["item"]))
        if isinstance(row, dict)
    ]

    def rank(row: dict) -> tuple:
        status = json_text(row.get("현행연혁코드") or row.get("현행연혁구분"))
        status_rank = 0 if status == "현행" else 1 if status == "연혁" else 2
        name = json_text(row.get(meta["name"]))
        return (status_rank, -score_law_relevance(name, query))

    return sorted(rows, key=rank)


def _json_total(data: dict, root_key: str) -> int:
    block = data.get(root_key) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return 0
    for key in ("totalCnt", "totalcnt", "총건수"):
        raw = json_text(block.get(key))
        if raw.isdigit():
            return int(raw)
    return 0


def _xml_hits(root, source: str) -> list[dict]:
    meta = CASE_SOURCES[source]
    hits = []
    for node in api.iter_xml_items(root, meta["item"]):
        item_id = api._find_text(node, meta["id"])
        title = api._find_text(node, meta["title"])
        number = api._find_text(node, meta["number"])
        date = api._find_text(node, meta["date"])
        extra = api._find_text(node, "법원명")
        blob = " ".join(part for part in (title, number, date, extra) if part)
        summary = title or item_id
        if number:
            summary = f"{summary} · {number}"
        hits.append({"id": item_id, "summary": summary, "blob": blob})
    return hits


def _ordin_hits(data: dict) -> list[dict]:
    meta = RESOURCE_CATEGORIES["ordin"]
    block = data.get(meta["root"]) if isinstance(data, dict) else None
    if not isinstance(block, dict):
        return []
    hits = []
    for row in _as_list(block.get(meta["item"])):
        if not isinstance(row, dict):
            continue
        name = json_text(row.get(meta["name"]))
        org = json_text(row.get(meta["organization"]))
        item_id = json_text(row.get(meta["id"]))
        summary = name or item_id
        if org:
            summary = f"{summary} · {org}"
        hits.append(
            {
                "id": item_id,
                "summary": summary,
                "blob": " ".join(part for part in (name, org) if part),
            }
        )
    return hits


def parse_bucket(hits: list[dict], search_count: int, anchor: dict, max_items: int) -> dict:
    judged = [
        (hit, classify_article_refs(hit.get("blob") or "", anchor)) for hit in hits
    ]
    kept = [
        pair
        for pair in judged
        if pair[1] not in ("mismatch", "law-mismatch")
    ]
    return {
        "verified": len(kept),
        "search_count": search_count,
        "top_items": [hit["summary"][:150] for hit, _ in kept[:max_items]],
        "excluded_article": sum(1 for _, verdict in judged if verdict == "mismatch"),
        "excluded_law": sum(1 for _, verdict in judged if verdict == "law-mismatch"),
        "covered": len(hits) >= search_count if search_count else True,
        "law_confirmed": sum(1 for _, verdict in judged if verdict == "match"),
        "law_held": sum(
            1 for _, verdict in judged if verdict in ("hold", "silent")
        ),
    }


def _bucket_line(stat: dict) -> str:
    parts = []
    if stat["excluded_article"]:
        parts.append(f"조문 불일치 {stat['excluded_article']}건")
    if stat["excluded_law"]:
        parts.append(f"다른 법령 {stat['excluded_law']}건")
    excl = f" ({'·'.join(parts)} 제외)" if parts else ""
    if stat["covered"]:
        return f"{stat['verified']}건{excl}"
    sampled = stat["verified"] + stat["excluded_article"] + stat["excluded_law"]
    return (
        f"{stat['verified']}건 확인{excl} / 검색 {stat['search_count']}건 — "
        f"표본 {sampled}건만 경계 확인, 나머지는 미확인"
    )


def _mermaid(center_label: str, counts: dict, cited: list[str]) -> str:
    center = "".join(
        ch if ch.isalnum() else "_" for ch in center_label
    )[:20] or "CENTER"
    lines = ["graph LR", f'    {center}["{center_label}"]']
    mapping = (
        ("precedents", "대법원 판례"),
        ("constitutional", "헌재 결정"),
        ("interpretations", "법령해석"),
        ("appeals", "행정심판"),
        ("ordinances", "자치법규"),
    )
    for key, label in mapping:
        count = counts.get(key) or 0
        if count:
            lines.append(f'    {center} --> {key[0].upper()}["{label} {count}건"]')
    for index, name in enumerate(cited[:5]):
        lines.append(f'    {center} -.인용.-> L{index}["{name}"]')
    return "\n".join(lines)


def run_impact_map(
    oc_key: str,
    law_name: str,
    jo: str,
    include_ordinances: bool = True,
) -> str:
    parsed = parse_article_anchor(jo)
    if parsed is None:
        return (
            f"[INVALID_ARGUMENT] 조문 번호 '{jo}'을(를) 해석하지 못했습니다. "
            "지원 형식: '제103조', '제10조의2', 또는 6자리 JO 코드 '010300'."
        )
    jo_display = parsed["display"]
    data = api.search_resource(oc_key, "law", law_name, display=20)
    rows = _law_rows(data, law_name)
    if not rows:
        return (
            f"{_NOT_FOUND} '{law_name}' 법령을 찾지 못했습니다. "
            "search_law로 정식 법령명을 확인하세요. 추측하지 마세요."
        )
    top = rows[0]
    official = json_text(top.get("법령명한글"))
    short = json_text(top.get("법령약칭명"))
    if not resolved_law_matches(law_name, official, short):
        return (
            f"{_NOT_FOUND} '{law_name}' 법령을 정확히 찾지 못했습니다. "
            f"검색 최상위는 '{official}'이지만 요청한 법령과 다를 수 있습니다. "
            "search_law로 정식 법령명을 확인한 뒤 다시 호출하세요."
        )
    law_id = json_text(top.get("법령ID"))
    anchor = dict(parsed)
    anchor["law_name"] = official
    search_query = f"{official} {jo_display}"

    article_text = ""
    try:
        payload = api.get_law_article(oc_key, law_id, parsed["code"])
        article_text = extract_law_article(payload, parsed["code"])
    except Exception:
        article_text = ""

    results: dict[str, tuple[list[dict], int]] = {}

    def fetch_xml(source: str) -> tuple[str, list[dict], int]:
        root = api.search_list(
            oc_key,
            query=search_query,
            search=2,
            display=10,
            target=source,
        )
        hits = _xml_hits(root, source)
        total = api.xml_total_count(root) or len(hits)
        return source, hits, total

    def fetch_ordin() -> tuple[str, list[dict], int]:
        payload = api.search_resource(
            oc_key, "ordin", search_query, display=10
        )
        hits = _ordin_hits(payload)
        total = _json_total(payload, RESOURCE_CATEGORIES["ordin"]["root"]) or len(
            hits
        )
        return "ordin", hits, total

    jobs = [source for source, _label, _max_items in _BUCKETS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch_xml, source) for source in jobs]
        if include_ordinances:
            futures.append(pool.submit(fetch_ordin))
        for future in as_completed(futures):
            source, hits, total = future.result()
            results[source] = (hits, total)

    stats: dict[str, dict] = {}
    for source, _label, max_items in _BUCKETS:
        hits, total = results.get(source, ([], 0))
        stats[source] = parse_bucket(hits, total, anchor, max_items)
    if include_ordinances:
        hits, total = results.get("ordin", ([], 0))
        stats["ordin"] = parse_bucket(hits, total, anchor, 5)

    cited = extract_cited_laws(article_text) if article_text else []
    lines = [
        f"[영향 맵] {official} {jo_display}",
        f"법령: {official} (id={law_id})",
        "",
    ]
    if article_text.strip():
        snippet = article_text.strip()[:400].replace("\n\n", "\n")
        suffix = "..." if len(article_text) > 400 else ""
        lines.append("대상 조문 본문")
        lines.append(snippet + suffix)
        lines.append("")
    else:
        lines.append(
            "대상 조문 본문 [NOT_FOUND] 조문 조회 실패 — 법령명·조문번호 확인 필요"
        )
        lines.append("")

    rows_out = [
        ("prec", "대법원 판례"),
        ("detc", "헌재 결정례"),
        ("expc", "법령해석례"),
        ("decc", "행정심판례"),
    ]
    if include_ordinances:
        rows_out.append(("ordin", "자치법규(법령 단위·조번호 미반영)"))

    lines.append("영향 그래프 (이 조문이 인용된 곳)")
    for index, (source, label) in enumerate(rows_out):
        last = index == len(rows_out) - 1
        prefix = "└─" if last else "├─"
        indent = "    " if last else "│   "
        stat = stats[source]
        lines.append(f"{prefix} {label}: {_bucket_line(stat)}")
        for item in stat["top_items"]:
            lines.append(f"{indent}· {item}")

    excluded_article = sum(stat["excluded_article"] for stat in stats.values())
    excluded_law = sum(stat["excluded_law"] for stat in stats.values())
    if excluded_article + excluded_law:
        parts = []
        if excluded_article:
            parts.append(f"조문 불일치 {excluded_article}건")
        if excluded_law:
            parts.append(f"다른 법령 {excluded_law}건")
        lines.append(
            f"법제처 키워드 검색은 조번호를 부분 일치로 물어옵니다"
            f"({jo_display} 질의에 유사 조번호·타 법령 혼입). "
            f"{'·'.join(parts)}을 제외했습니다."
        )
    confirmed = sum(stat["law_confirmed"] for stat in stats.values())
    held = sum(stat["law_held"] for stat in stats.values())
    lines.append(
        f"법령명 대조: 확정 {confirmed}건 / 보류 {held}건 "
        "(보류는 약칭·표기 변형으로 판정 불가 — 제외하지 않고 유지하므로 "
        "타 법령이 섞였을 수 있음)"
    )
    if cited:
        lines.append("")
        lines.append("이 조문이 인용한 다른 법령 (정방향)")
        for name in cited:
            lines.append(f"  → {name}")

    total = sum(stats[source]["verified"] for source, _ in rows_out)
    partial = any(not stats[source]["covered"] for source, _ in rows_out)
    extra = " — 표본을 넘는 검색 결과가 있어 실제는 더 많을 수 있음" if partial else ""
    ordin_n = stats.get("ordin", {}).get("verified", 0) if include_ordinances else 0
    lines.append("")
    lines.append(
        f"총 영향 건수(경계 확인분): {total}건{extra} "
        f"(판례 {stats['prec']['verified']} / 헌재 {stats['detc']['verified']} / "
        f"해석 {stats['expc']['verified']} / 행심 {stats['decc']['verified']}"
        + (f" / 조례 {ordin_n}" if include_ordinances else "")
        + ")"
    )
    lines.append(f"인용 법령: {len(cited)}개")
    lines.append("")
    mermaid = _mermaid(
        f"{official} {jo_display}",
        {
            "precedents": stats["prec"]["verified"],
            "constitutional": stats["detc"]["verified"],
            "interpretations": stats["expc"]["verified"],
            "appeals": stats["decc"]["verified"],
            "ordinances": ordin_n,
        },
        cited,
    )
    lines.append("Mermaid 그래프")
    lines.append("```mermaid")
    lines.append(mermaid)
    lines.append("```")
    lines.append("")
    lines.append("이어서 할 수 있는 조회")
    lines.append(f'1. search_cases("{official} {jo_display}", source=prec)')
    lines.append(f'2. search_cases("{official} {jo_display}", source=expc)')
    lines.append("3. compare_old_new — 개정 이력")
    return "\n".join(lines)
