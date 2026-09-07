"""자치법규 본문도 항ㆍ호ㆍ목이 줄로 나뉘는지 검증."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab


ROW = {
    "target": "ordin",
    "label": "자치법규",
    "id": "1234567",
    "name": "이천시 도시계획 조례",
    "related": "",
    "organization": "이천시",
    "date": "",
    "number": "",
    "effective": "",
    "short_name": "",
    "raw": {},
}

ARTICLE = (
    "제5조(도시계획위원회의 구성) ① 위원회는 위원장 1명을 포함한 15명 이내의 "
    "위원으로 구성한다. ② 위원은 다음 각 호의 사람 중에서 시장이 위촉한다. "
    "1. 시의회 의원 2. 관계 공무원 3. 도시계획에 관한 학식과 경험이 풍부한 사람"
)


def _tab(tmp_path) -> ResourceSearchTab:
    QApplication.instance() or QApplication([])
    settings = QSettings(
        str(tmp_path / "ordin.ini"), QSettings.Format.IniFormat
    )
    return ResourceSearchTab(
        lambda: "test-oc",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )


def test_ordinance_article_is_split_into_paragraph_lines(tmp_path) -> None:
    tab = _tab(tmp_path)
    tab.pending_row = dict(ROW)
    payload = {
        "LawService": {
            "자치법규기본정보": {
                "자치법규명": ROW["name"],
                "지자체기관명": "이천시",
            },
            "조문": {"조": [{"조내용": ARTICLE}]},
        }
    }

    _title, _metadata, sections = tab._parse_ordin_detail(payload)
    lines = sections[0][1].splitlines()

    assert lines[0].startswith("제5조(도시계획위원회의 구성)")
    assert lines[1].startswith("①")
    assert lines[2].startswith("②")
    assert lines[3].startswith("1.")
    assert lines[4].startswith("2.")
    assert lines[5].startswith("3.")
