"""3단비교(법률-시행령-시행규칙) 응답을 짧은 평문으로 줄인다.

화면 팝업은 3열 HTML이 필요하지만, AI 도구에는 위임된 하위법령 이름과
조 대응만 있으면 된다. 전문을 넣지 않는다.
"""

from __future__ import annotations

from utils.parsing import json_list, json_text


def three_stage_comparison_body(payload: dict) -> dict:
    """위임조문 삼단비교 본문을 찾는다. 없으면 인용조문으로 본다."""
    service = next(
        (
            value
            for value in payload.values()
            if isinstance(value, dict)
            and (
                "위임조문삼단비교" in value
                or "인용조문삼단비교" in value
            )
        ),
        None,
    )
    if not isinstance(service, dict):
        return {}
    comparison = service.get("위임조문삼단비교")
    if not isinstance(comparison, dict):
        comparison = service.get("인용조문삼단비교")
    return comparison if isinstance(comparison, dict) else {}


def _child_nodes(value: object) -> list[dict]:
    if isinstance(value, list):
        nodes: list[dict] = []
        for item in value:
            nodes.extend(_child_nodes(item))
        return nodes
    if not isinstance(value, dict):
        return []
    if any(key in value for key in ("조제목", "조내용", "조번호")):
        return [value]
    nodes: list[dict] = []
    for nested in value.values():
        nodes.extend(_child_nodes(nested))
    return nodes


def _article_label(node: dict) -> str:
    number = json_text(node.get("조번호"))
    branch = json_text(node.get("조가지번호"))
    if not number:
        return ""
    digits = "".join(ch for ch in number if ch.isdigit())
    if not digits:
        return ""
    label = f"제{int(digits)}조"
    branch_digits = "".join(ch for ch in branch if ch.isdigit())
    if branch_digits and int(branch_digits):
        label += f"의{int(branch_digits)}"
    return label


def compact_three_stage(payload: object, *, limit: int = 12) -> str:
    """상위 법률 조와 위임된 시행령·시행규칙을 짧게 적는다."""
    if not isinstance(payload, dict):
        return ""
    comparison = three_stage_comparison_body(payload)
    articles = [
        article
        for article in json_list(comparison.get("법률조문"))
        if isinstance(article, dict)
    ]
    if not articles:
        return ""
    subordinates: list[str] = []
    seen_names: set[str] = set()
    lines: list[str] = []
    for article in articles:
        law_label = _article_label(article)
        if not law_label:
            continue
        mapped: list[str] = []
        for key, kind in (
            ("시행령조문", "시행령"),
            ("시행령조문목록", "시행령"),
            ("시행규칙조문", "시행규칙"),
            ("시행규칙조문목록", "시행규칙"),
        ):
            for node in _child_nodes(article.get(key)):
                name = json_text(node.get("법령명"))
                if name and name not in seen_names:
                    seen_names.add(name)
                    subordinates.append(name)
                child_label = _article_label(node)
                title = json_text(node.get("조제목"))
                piece = kind
                if child_label:
                    piece += f" {child_label}"
                if title:
                    piece += f"({title})"
                if piece not in mapped:
                    mapped.append(piece)
        if mapped:
            lines.append(f"- {law_label} → {', '.join(mapped)}")
        if len(lines) >= limit:
            break
    if not lines and not subordinates:
        return ""
    header = ["[3단비교 위임]"]
    if subordinates:
        header.append("하위: " + ", ".join(subordinates))
    if len(articles) > limit and len(lines) >= limit:
        lines.append(f"(법률 조 {len(articles)}건 중 앞 {limit}건만 표시)")
    lines.append(
        "위임된 시행령·시행규칙 조는 get_article로 읽고 답하십시오."
    )
    return "\n".join(header + lines)
