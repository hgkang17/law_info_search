from __future__ import annotations

from types import SimpleNamespace

from ui.tabs.resource_search import (
    LAW_RENDER_SNAPSHOT_VERSION,
    ResourceSearchTab,
)


def test_restoring_saved_body_preserves_existing_tab_scroll() -> None:
    key = "law:009419"
    state: dict[str, object] = {"scroll": 437}
    tab = SimpleNamespace(
        detail_font_size=10.0,
        highlight_terms=(),
        _active_document_key=key,
        _document_states={key: state},
        _open_document_tab=lambda _row, defer_restore=False: None,
        _cached_memos_for_state=lambda _record: [],
        _restore_document_state=lambda _key: None,
        _queue_three_stage_link_request=lambda _name: None,
    )
    record = {
        "render_snapshot_version": LAW_RENDER_SNAPSHOT_VERSION,
        "rendered_html": "<p>본문</p>",
        "rendered_plain_text": "본문",
        "rendered_toc_entries": [],
        "rendered_three_stage_articles": [],
        "render_highlight_terms": [],
        "rendered_font_size": 10.0,
        "name": "국토의 계획 및 이용에 관한 법률 시행령",
    }

    restored = ResourceSearchTab._restore_cached_law_render(
        tab,
        {"target": "law", "id": "009419", "name": record["name"]},
        record,
    )

    assert restored is True
    assert state["scroll"] == 437

