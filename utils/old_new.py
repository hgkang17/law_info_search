"""신구법 대조 XML을 AI가 읽을 짧은 평문으로 줄인다."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET


def _local(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _child_text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    for child in node.iter():
        if _local(child.tag) == tag:
            return "".join(child.itertext()).strip()
    return ""


def _clean_clause(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value or "")
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(text.split())


def _articles(root: ET.Element | None) -> list[tuple[str, str]]:
    if root is None:
        return []
    items: list[tuple[str, str]] = []
    for node in list(root):
        if _local(node.tag) != "조문":
            continue
        title = _child_text(node, "조문키") or _child_text(node, "조문번호") or ""
        body = _clean_clause("".join(node.itertext()))
        if title or body:
            items.append((title, body))
    return items


def compact_old_new_xml(root: ET.Element, *, limit: int = 12) -> str:
    law_name = _child_text(root, "법령명") or "법령"
    old_info = None
    new_info = None
    old_list = None
    new_list = None
    for node in root.iter():
        name = _local(node.tag)
        if name == "구조문_기본정보" and old_info is None:
            old_info = node
        elif name == "신조문_기본정보" and new_info is None:
            new_info = node
        elif name == "구조문목록" and old_list is None:
            old_list = node
        elif name == "신조문목록" and new_list is None:
            new_list = node
    revision = _child_text(new_info, "제개정구분명")
    old_date = _child_text(old_info, "공포일자")
    new_date = _child_text(new_info, "공포일자")
    old_articles = _articles(old_list)
    new_articles = _articles(new_list)
    if not old_articles and not new_articles:
        return ""
    lines = [f"[신구대조] {law_name}"]
    if revision:
        lines.append(f"개정구분: {revision}")
    if old_date or new_date:
        lines.append(f"구법 공포일 {old_date or '-'} → 신법 공포일 {new_date or '-'}")
    count = max(len(old_articles), len(new_articles))
    for index in range(min(count, limit)):
        old_title, old_body = old_articles[index] if index < len(old_articles) else ("", "")
        new_title, new_body = new_articles[index] if index < len(new_articles) else ("", "")
        label = new_title or old_title or f"조문 {index + 1}"
        lines.append(f"- {label}")
        if old_body:
            lines.append(f"  구: {old_body[:400]}")
        if new_body:
            lines.append(f"  신: {new_body[:400]}")
    if count > limit:
        lines.append(f"… 나머지 {count - limit}개 조문은 생략")
    return "\n".join(lines)
