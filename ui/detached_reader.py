"""분리 창에서도 자료 종류별 원래 본문 컨트롤러와 위젯을 사용한다."""

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QTextDocument


_retired_pages = set()


def retain_busy_page(page):
    """창은 즉시 닫되 다운로드 중인 QThread의 부모는 완료까지 살려 둔다."""
    workers = [worker for worker in page.findChildren(QThread) if worker.isRunning()]
    if not workers:
        return False
    page.hide()
    page.setParent(None)
    _retired_pages.add(page)
    remaining = set(workers)

    def finished(worker):
        remaining.discard(worker)
        if not remaining:
            _retired_pages.discard(page)
            page.deleteLater()

    for worker in workers:
        worker.requestInterruption()
        worker.finished.connect(lambda target=worker: finished(target))
    return True


def attach_reader(page, source, payload):
    from ui.tabs.resource_search import ResourceSearchTab

    if getattr(page, "source_reader", None) is not None:
        return
    args = (source.oc_provider, source.recent_search_manager, source.law_cache)
    if isinstance(source, ResourceSearchTab):
        reader = ResourceSearchTab(*args, parent=page, settings=source.settings)
    else:
        reader = type(source)(source.service, *args, parent=page)
        reader.reference_tab = getattr(source, "reference_tab", None)
    reader.hide()
    page.source_reader = reader
    page.source_tab = source
    reader.detail_font_size = source.detail_font_size
    reader.detail_font_family = source.detail_font_family
    reader.detail_font_spin.blockSignals(True)
    reader.detail_font_spin.setValue(reader.detail_font_size)
    reader.detail_font_spin.blockSignals(False)
    from ui.widgets import select_detail_font_in_combo, DoubleClickLabel
    select_detail_font_in_combo(reader.detail_font_combo, reader.detail_font_family)

    page._clear_article_controls()
    old_splitter = page.reader_splitter
    position = page.layout().indexOf(old_splitter)
    page.layout().removeWidget(old_splitter)
    old_splitter.hide()
    reader.detail_card.setParent(page)
    page.layout().insertWidget(position, reader.detail_card, 1)
    reader.detail_card.layout().setContentsMargins(8, 8, 8, 8)
    reader.detail_card.show()
    # 검색 화면으로 돌아가는 단추와 중복 본문 탭은 창 바깥 탭이 맡는다.
    for name in ("restore_view_button", "expand_detail_button", "detail_button",
                 "document_tab_strip", "close_all_documents_button"):
        widget = getattr(reader, name, None)
        if widget is not None:
            widget.hide()
    reader._reading_mode = True
    reader.reading_mode_shortcut.setParent(page)
    reader.reading_mode_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
    reader.reading_mode_shortcut.activated.disconnect()
    reader.reading_mode_shortcut.activated.connect(lambda: page.window().toggle_maximized())
    title = reader.detail_card.findChild(DoubleClickLabel, "detailSectionTitle")
    if title is not None:
        title.doubleClicked.disconnect()
        title.doubleClicked.connect(lambda: page.window().toggle_maximized())
    page.browser = reader.detail_view
    page.search_bar = reader.detail_search
    page.reader_splitter = getattr(reader, "detail_content_splitter", reader.detail_card)

    if isinstance(reader, ResourceSearchTab):
        reader._detached_reader = True
        reader._law_short_name_cache.update(source._law_short_name_cache)
        # 받은 파일 목록은 본 창과 하나다. 어느 창에서 받든 같은 목록에
        # 쌓이고, 다운로드 단추는 이 창 머리글의 단추를 쓴다.
        reader._completed_downloads = source._completed_downloads
        reader._removed_downloads = source._removed_downloads
        reader._shared_download_source = source
        state = dict(payload["state"])
        document = state.get("document")
        # 원래 탭을 닫은 뒤 호출된다. 이미 뷰에서 떨어진 문서를 넘겨
        # 분리와 복귀 양쪽에서 HTML 파싱을 반복하지 않는다.
        state["document"] = document if isinstance(document, QTextDocument) else None
        reader.reattach_document({**payload, "state": state}, scroll=int(state.get("scroll") or 0))
        reader._restore_cached_document_controls(reader._active_document_key)
        page.toc_tree = reader.toc_tree
        page.toc_panel = reader.toc_panel
        page.toc_search_input = reader.toc_search_input
        reader.family_law_tree.itemDoubleClicked.disconnect()
        def open_family(item, column=0):
            name = str(item.data(0, Qt.ItemDataRole.UserRole) or "")
            QTimer.singleShot(0, page, lambda: source._open_detached_family_law(page, name))
        reader.family_law_tree.itemDoubleClicked.connect(open_family)
    else:
        document = source.detail_view.document().clone(reader)
        _install_snapshot_document(reader, document, payload["row"],
                                   payload.get("text", ""),
                                   getattr(source, "_visible_memos", []),
                                   payload.get("scroll", 0))
    bind = getattr(page.window(), "bind_download_tray", None)
    if callable(bind):
        bind(page)
    install_api_refresh_button(reader)
    sync_reader_state(page)


def _refreshable_row(reader):
    """이 창 본문을 API에서 다시 받을 수 있으면 그 행을, 아니면 None.

    본 창 ``LawSearchWindow._refreshable_open_document``와 같은 규칙이다.
    """
    from ui.tabs.resource_search import ResourceSearchTab

    if isinstance(reader, ResourceSearchTab):
        row = reader._document_tab_row(reader._active_document_key)
        if not isinstance(row, dict):
            return None
        target = str(row.get("target") or "")
        if target == "law_article":
            if not isinstance(row.get("source_row"), dict) or not isinstance(
                row.get("favorite_unit"), dict
            ):
                return None
        elif target not in {"law", "admrul", "ordin"}:
            return None
        return dict(row)
    row = getattr(reader, "_active_detail_row", None)
    if not isinstance(row, dict) or not row.get("detail_available"):
        return None
    return dict(row)


def install_api_refresh_button(reader):
    """본 창과 같은 'API 갱신' 단추를 이 창 본문 머리줄 맨 오른쪽에 단다."""
    from PySide6.QtWidgets import QPushButton
    from ui.tabs.resource_search import ResourceSearchTab

    if getattr(reader, "api_refresh_button", None) is not None:
        return reader.api_refresh_button
    # AI 조문 본문처럼 본 창에서도 갱신 대상이 아닌 화면에는 달지 않는다.
    if not isinstance(reader, ResourceSearchTab) and not hasattr(
        reader, "detail_head_layout"
    ):
        return None
    button = QPushButton("API\n갱신")
    button.setObjectName("openDocumentApiRefresh")
    button.setStyleSheet(
        "QPushButton#openDocumentApiRefresh {font-size:11px;"
        "line-height:12px; padding:1px 6px;}"
    )
    button.setFixedHeight(34)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip("이 본문을 API에서 다시 받아 화면과 저장본을 갱신합니다.")
    if isinstance(reader, ResourceSearchTab):
        reader.set_pinned_api_refresh_button(button)
    else:
        button.setParent(reader.detail_card)
        reader.detail_head_layout.addWidget(button)
    reader.api_refresh_button = button

    def busy():
        worker = getattr(reader, "worker", None)
        return bool(worker is not None and worker.isRunning())

    def sync():
        button.setEnabled(_refreshable_row(reader) is not None and not busy())

    def refresh():
        row = _refreshable_row(reader)
        if row is None or busy():
            return
        if isinstance(reader, ResourceSearchTab):
            if str(row.get("target") or "") == "law_article":
                reader.open_cached_favorite_article(
                    {"row": dict(row["source_row"]), "payload": {}},
                    dict(row["favorite_unit"]),
                    allow_full_fallback=False, force_api=True,
                )
            else:
                reader._request_resource_detail(row, force_api=True)
        else:
            reader._request_detail(row, force_api=True)
        worker = getattr(reader, "worker", None)
        if worker is not None and worker.isRunning():
            worker.finished.connect(sync)
        sync()

    button.clicked.connect(refresh)
    sync()
    return button


def sync_reader_state(page):
    reader = getattr(page, "source_reader", None)
    if reader is None:
        return
    payload = page.reattach_payload
    if payload.get("source") == "resource":
        reader._save_active_document_state()
        payload["state"] = dict(reader._document_states[reader._active_document_key])
    else:
        payload.update(html=reader.detail_view.toHtml(), text=reader.current_detail_text,
                       memos=[dict(m) for m in reader._visible_memos],
                       font_size=reader.detail_font_size, font_family=reader.detail_font_family)


def restore_reader_font(page, target):
    reader = getattr(page, "source_reader", None)
    if reader is None:
        return
    from ui.widgets import select_detail_font_in_combo
    target.detail_font_size = reader.detail_font_size
    target.detail_font_family = reader.detail_font_family
    target.detail_font_spin.blockSignals(True)
    target.detail_font_spin.setValue(reader.detail_font_size)
    target.detail_font_spin.blockSignals(False)
    select_detail_font_in_combo(target.detail_font_combo, reader.detail_font_family)


def _install_snapshot_document(reader, document, row, text, memos, scroll):
    document.setParent(reader)
    reader._active_detail_row = dict(row)
    reader.current_detail_text = str(text)
    reader.detail_view.setDocument(document)
    reader.detail_search.bind_document(document)
    reader.memo_marker_bar.bind_document(document)
    reader._set_visible_memos([dict(m) for m in memos])
    reader.copy_button.setEnabled(bool(text))
    update_article = getattr(reader, "_update_three_stage_button", None)
    if update_article is not None:
        update_article(reader._active_detail_row)
    bar = reader.detail_view.verticalScrollBar()
    bar.setValue(int(scroll))
    QTimer.singleShot(0, reader, lambda: bar.setValue(int(scroll)))


def restore_snapshot_reader(page, target, payload, scroll):
    reader = getattr(page, "source_reader", None)
    if reader is None:
        return False
    _install_snapshot_document(target, reader.detail_view.document(), payload["row"],
                               payload.get("text", ""), payload.get("memos", []), scroll)
    return True
