"""조문 영향 맵. 조문 경계와 법령명 가드."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import molit_cgm_expc_api as api
from llm.article_anchor import classify_article_refs, parse_article_anchor
from llm.impact_map import parse_bucket, run_impact_map


def test_parse_article_anchor_accepts_label_and_code() -> None:
    by_label = parse_article_anchor("제10조의2", "민법")
    by_code = parse_article_anchor("001002", "민법")
    assert by_label is not None and by_code is not None
    assert by_label["code"] == by_code["code"] == "001002"
    assert by_label["display"] == "제10조의2"
    assert parse_article_anchor("조문없음") is None


def test_classify_rejects_similar_article_number() -> None:
    anchor = parse_article_anchor("제103조", "민법")
    assert classify_article_refs("민법 제103조 위헌소원", anchor) == "match"
    assert classify_article_refs("민법 제1032조 위헌소원", anchor) == "mismatch"
    assert classify_article_refs("손해배상(기)", anchor) == "silent"
    assert (
        classify_article_refs("형법 제103조 관련", anchor) == "law-mismatch"
    )
    assert (
        classify_article_refs("제103조부터 제105조까지", anchor) == "match"
    )


def test_parse_bucket_keeps_silent_and_drops_mismatch() -> None:
    anchor = parse_article_anchor("제103조", "민법")
    hits = [
        {"summary": "민법 제103조", "blob": "민법 제103조 위헌소원"},
        {"summary": "민법 제1032조", "blob": "민법 제1032조 위헌소원"},
        {"summary": "손해배상", "blob": "손해배상(기)"},
    ]
    stat = parse_bucket(hits, search_count=3, anchor=anchor, max_items=5)
    assert stat["verified"] == 2
    assert stat["excluded_article"] == 1
    assert stat["law_confirmed"] == 1
    assert stat["law_held"] == 1


def _xml(tag: str, items: list[dict]) -> ET.Element:
    root = ET.Element("Search")
    ET.SubElement(root, "totalCnt").text = str(len(items))
    for item in items:
        node = ET.SubElement(root, tag)
        for key, value in item.items():
            ET.SubElement(node, key).text = value
    return root


def test_impact_map_filters_and_guards_law_name(monkeypatch) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        if target == "law":
            return {
                "LawSearch": {
                    "law": [
                        {
                            "법령명한글": "민법",
                            "법령ID": "000001",
                            "현행연혁코드": "현행",
                        }
                    ]
                }
            }
        return {"OrdinSearch": {"law": []}}

    def fake_get_law_article(oc, item_id, jo, **kwargs):
        return {
            "법령": {
                "조문": {
                    "조문단위": [
                        {
                            "조문키": "010300",
                            "조문번호": "103",
                            "조문내용": "제103조 반사회질서의 법률행위는 무효로 한다. 「형법」 참조.",
                        }
                    ]
                }
            }
        }

    def fake_search_list(oc, query=None, search=1, display=20, **kwargs):
        target = kwargs.get("target")
        if target == "prec":
            return _xml(
                "prec",
                [
                    {
                        "판례일련번호": "1",
                        "사건명": "민법 제103조 관련",
                        "사건번호": "2013다1",
                    },
                    {
                        "판례일련번호": "2",
                        "사건명": "민법 제1032조 위헌소원",
                        "사건번호": "2014헌바1",
                    },
                ],
            )
        empty_tag = {
            "detc": "detc",
            "expc": "expc",
            "decc": "decc",
        }[target]
        return _xml(empty_tag, [])

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    monkeypatch.setattr(api, "get_law_article", fake_get_law_article)
    monkeypatch.setattr(api, "search_list", fake_search_list)
    text = run_impact_map("dummy", "민법", "제103조")
    assert "[영향 맵] 민법 제103조" in text
    assert "민법 제103조 관련" in text
    assert "제1032조" not in text.split("영향 그래프")[-1].split("법령명 대조")[0]
    assert "형법" in text
    assert "조문 불일치 1건" in text


def test_impact_map_refuses_unrelated_top_hit(monkeypatch) -> None:
    def fake_search_resource(oc, target, query, **kwargs):
        return {
            "LawSearch": {
                "law": [
                    {
                        "법령명한글": "난민법",
                        "법령ID": "9",
                        "현행연혁코드": "현행",
                    }
                ]
            }
        }

    monkeypatch.setattr(api, "search_resource", fake_search_resource)
    text = run_impact_map("dummy", "민법", "000100")
    assert "[NOT_FOUND]" in text
    assert "난민법" in text
    assert "영향 그래프" not in text
