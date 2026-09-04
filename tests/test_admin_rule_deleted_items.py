import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from utils.formatting import body_to_html
from utils.parsing import insert_admin_clause_breaks, json_text

# body_to_html은 표식 폭을 QFontMetrics로 재므로 QApplication이 있어야
# 한다. 없으면 Qt가 프로세스를 그대로 끝내 버려 이어지는 테스트까지
# 함께 사라진다.
QApplication.instance() or QApplication([])


def test_json_text_preserves_deleted_admin_rule_marker() -> None:
    assert json_text("(4) <삭제><br>(5) 내용") == "(4) <삭제>\n(5) 내용"


def test_json_text_joins_api_string_lists() -> None:
    """조문내용이 XML 반복 노드면 JSON 배열로 온다. str(리스트)로 찍지 않는다."""
    assert json_text(["제1장 총칙", "제1조(목적) 이 지침은 규정한다."]) == (
        "제1장 총칙\n제1조(목적) 이 지침은 규정한다."
    )
    dumped = str(["제1장 총칙", "제1조(목적) 이 지침은 규정한다."])
    assert dumped.startswith("['")
    assert json_text(dumped) == "제1장 총칙\n제1조(목적) 이 지침은 규정한다."


def test_json_text_keeps_brackets_and_quotes_in_body() -> None:
    source = (
        "종류는 [별표 1]과 같다. "
        "(이하 '법'이라 한다) 제2조를 따른다."
    )
    assert json_text(source) == source


def test_json_text_repairs_list_dump_split_at_chapter() -> None:
    """제1장 앞에서 줄을 가른 구버전 캐시도 항목으로 되돌린다."""
    dumped = str(["제1장 총칙", "제1조(목적) 이 지침은 규정한다."])
    broken = insert_admin_clause_breaks(dumped)
    restored = json_text(broken)
    assert "['" not in restored
    assert "', '" not in restored
    assert restored.splitlines()[0] == "제1장 총칙"
    assert restored.splitlines()[1].startswith("제1조(목적)")


def test_normalize_repairs_cached_list_dump() -> None:
    from utils.parsing import normalize_admin_rule_text

    dumped = str(["제1장 총칙", "제1조(목적) 이 지침은 규정한다."])
    assert "['" in dumped
    restored = normalize_admin_rule_text(dumped)
    assert "['" not in restored
    assert "', '" not in restored
    assert restored.splitlines()[0] == "제1장 총칙"
    assert restored.splitlines()[1].startswith("제1조(목적)")


def test_normalize_repairs_list_dump_after_heading_breaks() -> None:
    from utils.parsing import normalize_admin_rule_text

    dumped = str(["제1장 총칙", "제1조(목적) 이 지침은 규정한다."])
    broken = insert_admin_clause_breaks(dumped)
    restored = normalize_admin_rule_text(broken)
    assert "['" not in restored
    assert "', '" not in restored
    assert restored.splitlines()[0] == "제1장 총칙"
    assert restored.splitlines()[1].startswith("제1조(목적)")


def test_deleted_markers_render_as_text_and_keep_item_boundaries() -> None:
    source = (
        "3-1-6-1. 일반적 고려사항\n"
        "(3) 관리지역을 구분한다.\n"
        "(4) <삭제>\n"
        "(5) 도시지역외의 지역\n"
        "(6) <삭제>\n"
        "(7) <삭제>\n"
        "3-1-6-2. 보전관리지역"
    )

    html = body_to_html(source, administrative_rule=True)
    # ``<삭제>``는 개정 표기와 같은 서식을 받아 꺾쇠만 한 겹 더 감싼다.
    # 표시되는 글자만 보려고 태그를 걷어 내고 센다.
    shown = re.sub(r"<[^>]+>", "", html)
    assert shown.count("&lt;삭제&gt;") == 3
    assert "(4)&nbsp;" in html
    assert "(5)&nbsp;" in html
    assert "(6)&nbsp;" in html
    assert "(7)&nbsp;" in html
    assert "3-1-6-2.&nbsp;" in html


def test_old_cache_with_missing_deleted_text_is_repaired() -> None:
    source = (
        "3-1-6-1. 일반적 고려사항\n"
        "(4) (5) 도시지역외의 지역\n"
        "(6) (7) 3-1-6-2. 보전관리지역"
    )

    assert insert_admin_clause_breaks(source).splitlines() == [
        "3-1-6-1. 일반적 고려사항",
        "(4) <삭제>",
        "(5) 도시지역외의 지역",
        "(6) <삭제>",
        "(7) <삭제>",
        "3-1-6-2. 보전관리지역",
    ]
