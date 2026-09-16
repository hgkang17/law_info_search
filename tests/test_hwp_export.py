"""법령 전문 HWPX 자체 생성 코드와 공식 사이트 저장 버튼 회귀 시험."""

from __future__ import annotations

import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from storage.cache import LawDocumentCache
from storage.recent import RecentSearchManager
from ui.tabs.resource_search import ResourceSearchTab
from utils.hwp_export import (
    default_export_name,
    law_export_blocks,
    save_law_hwpx,
)


PLAIN_TEXT = """[조문]
제1조(목적) 이 법은 국토의 지속가능한 발전을 도모함을 목적으로 한다.
제2장 국토계획의 수립
제6조(국토계획의 정의 및 구분) 국토계획이란 국토를 이용하는 계획을 말한다.
[부칙]
이 법은 공포한 날부터 시행한다."""


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def test_sections_and_divisions_become_headings() -> None:
    blocks = law_export_blocks(PLAIN_TEXT)

    levels = {block.text: block.level for block in blocks}
    assert levels["조문"] == 1
    assert levels["부칙"] == 1
    assert levels["제2장 국토계획의 수립"] == 2
    # 조문은 제목으로 올리지 않는다. 평문에서 조 제목과 내용이 한 줄이라
    # 통째로 제목이 되면 문서 개요가 본문으로 가득 찬다.
    assert levels[
        "제6조(국토계획의 정의 및 구분) 국토계획이란 국토를 이용하는 계획을 말한다."
    ] == 0


def test_export_name_drops_characters_a_path_cannot_hold() -> None:
    assert default_export_name("국토의 계획/이용에 관한 법률") == (
        "국토의 계획 이용에 관한 법률.hwpx"
    )
    assert default_export_name("") == "법령.hwpx"


def test_saved_file_is_a_hwpx_package_with_the_body(tmp_path) -> None:
    pytest.importorskip("hwpx", reason="기존 자체 생성 코드의 별도 의존성")
    target = tmp_path / "국토기본법.hwpx"

    saved = save_law_hwpx(
        target,
        "국토기본법",
        "[시행 2026. 1. 1.] [법률 제20000호, 2025. 7. 1., 일부개정]",
        PLAIN_TEXT,
    )

    assert saved.is_file()
    with zipfile.ZipFile(saved) as archive:
        names = set(archive.namelist())
        # HWPX는 ZIP 안에 XML을 담는 개방 형식이다. 한글이 열려면 아래
        # 항목이 모두 있어야 한다.
        assert {
            "mimetype",
            "version.xml",
            "Contents/header.xml",
            "Contents/section0.xml",
            "Contents/content.hpf",
            "META-INF/container.xml",
        } <= names
        assert archive.read("mimetype") == b"application/hwp+zip"
        body = archive.read("Contents/section0.xml").decode("utf-8")
    assert "국토기본법" in body
    assert "국토계획의 정의" in body
    assert "이 법은 공포한 날부터 시행한다." in body


def test_pinned_title_row_offers_the_hwp_button_for_a_law(qt_app, tmp_path, monkeypatch) -> None:
    """법령 본문을 열면 제목 줄 옆에 한글 저장 단추가 함께 뜬다."""
    settings = QSettings(
        str(tmp_path / "export.ini"), QSettings.Format.IniFormat
    )
    tab = ResourceSearchTab(
        lambda: "",
        RecentSearchManager(settings),
        LawDocumentCache(tmp_path / "saved"),
    )
    try:
        assert tab.hwp_export_button.isHidden()

        tab.pending_row = {
            "target": "law",
            "id": "001234",
            "label": "법령",
            "name": "국토기본법",
        }
        tab._show_detail(
            {
                "법령": {
                    "기본정보": {
                        "법령명_한글": "국토기본법",
                        "법령ID": "001234",
                        "법령명약칭": "국토법",
                        "시행일자": "20260101",
                        "공포일자": "20250701",
                        "공포번호": "20000",
                        "법종구분": "법률",
                        "제개정구분": "일부개정",
                    },
                    "조문": {
                        "조문단위": [
                            {
                                "조문번호": "1",
                                "조문내용": "제1조(목적) 이 법은 국토를 다룬다.",
                            }
                        ]
                    },
                }
            },
            save_cache=False,
        )
        qt_app.processEvents()

        # 사이트의 전문 HWPX를 받는 버튼이 제목 줄에 표시된다.
        assert not tab.hwp_export_button.isHidden()
        assert tab.HWP_EXPORT_BUTTON_ENABLED
        title, headline = tab._pinned_headline_parts()
        assert title == "국토기본법"
        assert headline.startswith("[시행 2026. 1. 1.]")

        started = []

        class StubSignal:
            def connect(self, _callback):
                pass

        class StubWorker:
            def __init__(self, law_id, name, date, path):
                self.details = (law_id, name, date, path)
                self.progress = StubSignal()
                self.succeeded = StubSignal()
                self.failed = StubSignal()
                self.finished = StubSignal()

            def start(self):
                started.append(self.details)

            def deleteLater(self):
                pass

        monkeypatch.setattr("ui.tabs.resource_search.LawHwpxDownloadWorker", StubWorker)
        monkeypatch.setattr(
            "ui.tabs.resource_search.QFileDialog.getSaveFileName",
            lambda *_args: (str(tmp_path / "official.hwpx"), ""),
        )
        tab.hwp_export_button.click()
        assert started == [
            ("001234", "국토기본법", "20260101", str(tmp_path / "official.hwpx"))
        ]
    finally:
        tab.close()
