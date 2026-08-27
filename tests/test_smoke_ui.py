"""리팩터링 회귀 테스트 - 주요 화면 동작 확인.

네트워크 없이, 저장해 둔 본문과 로컬 캐시만으로 실제 조작 경로를 밟는다.
파일을 패키지로 나눈 뒤에도 이 경로들이 그대로 동작해야 한다.

    python tests/test_smoke_ui.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from PySide6.QtCore import QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QCursor,
    QKeyEvent,
    QMouseEvent,
    QTextCursor,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(passed), detail))


def pump(app: QApplication, times: int = 4) -> None:
    for _ in range(times):
        app.processEvents()


def send_key(app: QApplication, widget, key) -> None:
    for kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
        app.sendEvent(
            widget, QKeyEvent(kind, key, Qt.KeyboardModifier.NoModifier)
        )
    pump(app)


def send_mouse(app: QApplication, widget, kind, local, glob, buttons) -> None:
    app.sendEvent(
        widget,
        QMouseEvent(
            kind, local, glob, Qt.MouseButton.LeftButton, buttons,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    pump(app, 2)


def main() -> int:
    app = QApplication.instance() or QApplication([])
    import molit_cgm_expc_qt as module

    window = module.LawSearchWindow()
    window.resize(1400, 900)
    window.show()
    pump(app)
    check("앱이 뜬다", window.isVisible())

    tabs = [window.tabs.widget(i) for i in range(window.tabs.count())]
    check(
        "precedent search has API refresh",
        window.prec_tab.search_refresh_button is not None,
    )
    check("탭이 모두 만들어진다", len(tabs) >= 6, f"{len(tabs)}개")

    res = window.resource_tab
    ai = window.ai_search_tab

    # --- 저장 본문 열기 ---------------------------------------------
    records = window.law_cache.list_records()
    check("저장된 본문이 있다", bool(records), f"{len(records)}건")
    if records:
        viewed = window.viewed_laws_tab
        opened: list[object] = []
        viewed.openRequested.connect(lambda rec: opened.append(rec))
        viewed.table.clearSelection()
        pump(app)
        viewed.table.selectRow(1)
        pump(app, 6)
        check("저장 목록을 누르면 본문이 열린다", bool(opened))
        check(
            "본문이 실제로 그려진다",
            len(res.detail_view.toPlainText()) > 1000,
            f"{len(res.detail_view.toPlainText())}자",
        )

        # 검색 결과에 저장된 항목을 놓고 눌러 본다
        rows = []
        for record in records:
            row = record.get("row")
            if isinstance(row, dict) and row.get("target") in ("law", "admrul"):
                rows.append(dict(row))
            if len(rows) >= 2:
                break
        if rows:
            res.result_rows = rows
            res.result_table.setRowCount(len(rows))
            pump(app)
            res.result_table.clearSelection()
            pump(app)
            res.result_table.selectRow(0)
            pump(app, 6)
            body = res.detail_view.toPlainText()
            check(
                "검색결과의 저장 항목은 안내 대신 본문이 뜬다",
                "본문 조회를 누르면" not in body and len(body) > 1000,
                f"{len(body)}자",
            )

    # --- 크게 보기 / 되돌아가기 --------------------------------------
    res.memo_marker_bar.set_memos(
        [{"start": 1, "end": 2, "excerpt": "본문", "text": "메모"}]
    )
    res._set_reading_mode(True)
    pump(app)
    check(
        "memo marker remains visible in reading mode",
        res.memo_marker_bar.isVisible() and bool(res.memo_marker_bar._marker_rects()),
    )
    check("크게 보기로 전환된다", res._reading_mode)
    # 탭 자체가 화면에 없을 수 있으므로 숨김 여부로 본다.
    check("◀ 버튼이 나타난다", not res.restore_view_button.isHidden())
    button = res.restore_view_button
    send_mouse(app, button, QEvent.Type.MouseButtonPress,
               button.rect().center(), button.mapToGlobal(button.rect().center()),
               Qt.MouseButton.LeftButton)
    send_mouse(app, button, QEvent.Type.MouseButtonRelease,
               button.rect().center(), button.mapToGlobal(button.rect().center()),
               Qt.MouseButton.NoButton)
    check("◀ 로 원래 화면으로 돌아온다", not res._reading_mode)

    # --- 본문 검색과 Esc ---------------------------------------------
    bar = res.detail_search
    bar.focus_query()
    check(
        "Ctrl+F keeps document painting enabled",
        bar.browser.updatesEnabled(),
    )
    bar.browser.setHtml("<p>준공검사 준공사진 준공검사</p>")
    pump(app)
    bar.query_input.setText("준공")
    bar.query_input.setFocus()
    pump(app)
    check("본문 검색이 일치를 찾는다", len(bar.matches) == 3, f"{len(bar.matches)}건")
    send_key(app, bar.query_input, Qt.Key.Key_Escape)
    check("Esc로 검색이 취소된다", bar.query_input.text() == "" and not bar.matches)

    res._set_reading_mode(True)
    pump(app)
    bar.query_input.setText("준공")
    bar.query_input.setFocus()
    pump(app)
    send_key(app, bar.query_input, Qt.Key.Key_Escape)
    check("Esc로 크게 보기가 꺼지지 않는다", res._reading_mode)
    res._set_reading_mode(False)
    pump(app)

    # --- 조문 팝업과 하단 기록바 ---------------------------------------
    popup = res.reference_popup
    popup.pin_button.setChecked(True)
    popup.show_content_at("시험", "<p>본문</p>", QPoint(400, 400))
    pump(app)
    check("조문 팝업이 뜬다", popup.isVisible())
    QCursor.setPos(popup.frameGeometry().center())
    pump(app)
    send_key(app, res.detail_view, Qt.Key.Key_Escape)
    check("커서가 올라간 팝업이 Esc로 닫힌다",
          not popup.isVisible() and not popup.pin_button.isChecked())

    history = res.reference_tabs
    before = history.count()
    res._law_short_name_cache["국토의계획및이용에관한법률"] = "국토계획법"
    res._pending_delegation_source = {}
    res._remember_reference_popup(
        {"id": "009294", "name": "국토의 계획 및 이용에 관한 법률"},
        "제목", "<p>a</p>", "001900", "000100", "000100", "",
    )
    res._pending_delegation_source = {
        "label": "제3조의2제2항",
        "name": "국토의 계획 및 이용에 관한 법률",
        "authority": "대통령령",
    }
    res._remember_reference_popup(
        {"id": "009419", "name": "국토의 계획 및 이용에 관한 법률 시행령"},
        "제목", "<p>a</p>", "000400", "", "", "",
    )
    res._pending_delegation_source = {}
    pump(app)
    labels = [history.tabText(i) for i in range(history.count())]
    check("하단 기록이 쌓인다", history.count() >= before + 2, f"{history.count()}개")
    check("공식 약칭으로 적힌다",
          any(text.startswith("국토계획법 제19조") for text in labels), str(labels))
    check("위임 링크는 출처 조문으로 적힌다",
          "국토계획법 제3조의2제2항 대통령령" in labels, str(labels))
    check("이름이 잘리지 않는다", all("…" not in text for text in labels))

    if history.count() >= 2:
        chip = history._chips[0]
        last = history._chips[-1]
        first_text = history.tabText(0)
        center = chip.rect().center()
        send_mouse(app, chip, QEvent.Type.MouseButtonPress, center,
                   chip.mapToGlobal(center), Qt.MouseButton.LeftButton)
        send_mouse(app, chip, QEvent.Type.MouseMove, center + QPoint(40, 0),
                   last.mapToGlobal(last.rect().center()), Qt.MouseButton.LeftButton)
        moved_away = chip.pos() != QPoint(2, 2)
        send_mouse(app, chip, QEvent.Type.MouseButtonRelease, center + QPoint(40, 0),
                   last.mapToGlobal(last.rect().center()), Qt.MouseButton.NoButton)
        check("하단 기록을 끌면 순서가 바뀐다", history.tabText(0) != first_text)
        check("끄는 동안 칩이 커서를 따라온다", moved_away)

    # --- 음영 규칙 ----------------------------------------------------
    res.highlight_terms = ("국토의",)
    header, _ = res._detail_header("국토의 계획 및 이용에 관한 법률", [("법령ID", "009294")])
    check("법령 검색은 본문에 음영을 넣지 않는다", "#ffe58f" not in "".join(header))
    check("키워드 검색은 본문 음영을 유지한다",
          not hasattr(ai, "detail_highlight_terms"))

    # --- 칠한 서식이 문서를 오가도 남는가 ----------------------------
    # 문서 상태를 저장할 때 바뀐 적 없는 문서는 HTML을 다시 뽑지 않는데,
    # 사용자가 칠한 색까지 빠뜨리면 안 된다.
    if records and len(res.result_rows) >= 2:
        res.result_table.selectRow(0)
        pump(app, 6)
        cursor = res.detail_view.textCursor()
        cursor.setPosition(1)
        cursor.setPosition(20, QTextCursor.MoveMode.KeepAnchor)
        res.detail_view.setTextCursor(cursor)
        res._apply_palette_color("#ffe58f", background=True)
        # 문서 탭을 떠났다가 돌아오는 경로(파일을 다시 읽지 않는다)
        active_index = res.document_tabs.currentIndex()
        res._activate_preview()
        pump(app, 4)
        res._activate_document_tab(active_index)
        pump(app, 4)
        probe = QTextCursor(res.detail_view.document())
        probe.setPosition(5)
        background = probe.charFormat().background()
        kept = background.color()
        check(
            "칠한 음영이 문서를 오가도 남는다",
            background.style() != Qt.BrushStyle.NoBrush and kept.alpha() > 0,
            kept.name(QColor.NameFormat.HexArgb),
        )

    # --- 본문 그리기 --------------------------------------------------
    # 탭마다 본문 HTML을 실제로 한 번 넣어 본다. 파일을 나누며 공용
    # 헬퍼 임포트가 빠지면 여기서 NameError로 바로 드러난다.
    sample_html = (
        "<p style=\"font-size:10pt\">제1조(목적) 이 법은 국토의 이용을 규정한다.</p>"
    )
    for name, tab in (("법령검색", res), ("키워드검색", ai),
                      ("중앙부처", window.central_tab)):
        try:
            tab._replace_detail_content(html=sample_html, source_font_size=10)
            drawn = "제1조" in tab.detail_view.toPlainText()
            detail = ""
        except Exception as exc:
            drawn = False
            detail = f"{type(exc).__name__}: {exc}"
        check(f"{name} 본문이 그려진다", drawn, detail)

    # --- 더블클릭 ----------------------------------------------------
    for name, tab in (("법령검색", res), ("키워드검색", ai),
                      ("중앙부처", window.central_tab)):
        check(f"{name} 더블클릭 핸들러가 있다", hasattr(tab, "_open_detail_expanded"))
    check("상단 문서 탭을 옮길 수 있다", res.document_tabs.isMovable())

    # --- 결과 --------------------------------------------------------
    failed = [item for item in RESULTS if not item[1]]
    for name, passed, detail in RESULTS:
        mark = "  OK  " if passed else "**FAIL**"
        suffix = f"  ({detail})" if detail else ""
        print(f"{mark} {name}{suffix}")
    print()
    print(f"{len(RESULTS) - len(failed)}/{len(RESULTS)} 통과")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
