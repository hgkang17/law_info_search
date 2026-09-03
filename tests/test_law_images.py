"""법령 조문 안의 법제처 표·도면 이미지 회귀 테스트."""

from __future__ import annotations

import base64
from types import SimpleNamespace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

import molit_cgm_expc_api as api
from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.formatting import body_to_html
from utils.parsing import admin_rule_plain_text, law_article_text, law_text


BUILDING_DECREE_TABLE = (
    '2. 막다른 도로의 길이가 다음 표의 구분에 따른 길이 이상인 경우'
    '<img src="http://www.law.go.kr/flDownload.do?flSeq=22909013" '
    'alt="막다른 도로의 길이별 도로의 너비 표">'
    '┌──────────┬──────────┐\n'
    '│막다른 도로의 길이│도로의 너비│\n'
    '├──────────┼──────────┤\n'
    '│10미터 미만│2미터│\n'
    '└──────────┴──────────┘'
    '</img>'
)


def _law_payload(source: str = BUILDING_DECREE_TABLE) -> dict:
    return {
        "법령": {
            "조문": {
                "조문단위": {
                    "조문내용": "제3조의3(지형적 조건 등에 따른 도로의 구조와 너비)",
                    "항": {"항내용": "① 다음 각 호의 어느 하나", "호": {"호내용": source}},
                }
            }
        }
    }


def test_law_text_replaces_inner_box_drawing_with_image_marker() -> None:
    text = law_article_text(_law_payload()["법령"]["조문"]["조문단위"])

    assert "[[LAW_IMAGE:22909013]]" in text
    assert "┌" not in text
    assert "│" not in text
    assert "막다른 도로의 길이│" not in text
    assert "2. 막다른 도로의 길이" in text


def test_law_text_preserves_unknown_image_fallback_and_handles_id_tag() -> None:
    assert law_text('<img alt="표">대체 표 내용</img>') == "대체 표 내용"
    assert law_text('<img id="12345"></img>') == "[[LAW_IMAGE:12345]]"


def test_attach_law_images_downloads_each_flseq_once(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(_url, params, **_kwargs):
        image_id = str(params["flSeq"])
        calls.append(image_id)
        return SimpleNamespace(
            content=f"gif-{image_id}".encode(),
            headers={"Content-Type": "image/gif;charset=UTF-8"},
        )

    monkeypatch.setattr(api, "_request", fake_request)
    payload = _law_payload(BUILDING_DECREE_TABLE + BUILDING_DECREE_TABLE)

    returned = api.attach_law_images(payload)

    assert returned is payload
    assert calls == ["22909013"]
    assert payload[api.LAW_IMAGES_VERSION_KEY] == api.LAW_IMAGES_VERSION
    embedded = payload[api.ADMIN_RULE_IMAGES_KEY]
    assert base64.b64decode(embedded["22909013"].split(",", 1)[1]) == (
        b"gif-22909013"
    )
    assert not api.law_payload_images_need_refresh(payload)


def test_legacy_law_payload_with_image_needs_one_refresh() -> None:
    payload = _law_payload()

    assert api.law_payload_image_ids(payload) == ["22909013"]
    assert api.law_payload_images_need_refresh(payload)
    assert not api.law_payload_images_need_refresh(_law_payload("이미지 없는 본문"))


def test_law_image_marker_renders_in_place_and_stays_out_of_plain_text() -> None:
    _app = QApplication.instance() or QApplication([])
    image_uri = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
    text = law_text(BUILDING_DECREE_TABLE)

    rendered = body_to_html(
        text,
        embedded_images={"22909013": image_uri},
    )

    assert f'src="{image_uri}"' in rendered
    assert "┌" not in rendered
    assert "[[LAW_IMAGE:" not in rendered
    assert admin_rule_plain_text(text).endswith("[원문 표 이미지]")


def test_law_detail_screen_uses_embedded_image_without_box_text(tmp_path) -> None:
    _app = QApplication.instance() or QApplication([])
    image_uri = "data:image/gif;base64,R0lGODlhAQABAAAAACw="
    payload = _law_payload()
    payload["법령"]["기본정보"] = {
        "법령명_한글": "건축법 시행령",
        "법령ID": "002118",
    }
    payload[api.ADMIN_RULE_IMAGES_KEY] = {"22909013": image_uri}
    payload[api.LAW_IMAGES_VERSION_KEY] = api.LAW_IMAGES_VERSION
    settings = QSettings(
        str(tmp_path / "law-images.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    tab.pending_row = {
        "target": "law",
        "id": "002118",
        "label": "법령",
        "name": "건축법 시행령",
    }

    tab._show_detail(payload, save_cache=False)

    source_html = str(
        tab._document_states[tab._active_document_key]["source_html"]
    )
    assert f'src="{image_uri}"' in source_html
    assert "┌" not in source_html
    assert "[[LAW_IMAGE:" not in source_html
    assert "[원문 표 이미지]" in tab.current_detail_text
    tab.close()
