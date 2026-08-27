import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtPdf import QPdfDocument

from ui.dialogs import PdfPreviewPopup


def test_pdf_preview_uses_resizable_non_modal_tool_popup():
    app = QApplication.instance() or QApplication([])
    popup = PdfPreviewPopup()
    popup.show()
    app.processEvents()

    assert not isinstance(popup, QDialog)
    assert popup.isWindow()
    assert popup.pin_button.isChecked()
    assert popup.pin_button.text() == "고정됨"
    assert popup.zoom_spin.singleStep() == 5
    assert len(popup.resize_handles) == 8
    assert all(handle.isVisible() for handle in popup.resize_handles)
    assert popup.arrow_drag_bar.height() == 22
    assert popup.drag_bar.height() == 38

    popup._adjust_zoom(5)
    assert popup.zoom_spin.value() == 105
    assert popup.pdf_view.zoomFactor() == 1.05
    popup._adjust_zoom(-10)
    assert popup.zoom_spin.value() == 95
    assert popup.pdf_view.zoomFactor() == 0.95

    popup._on_document_status_changed(QPdfDocument.Status.Ready)
    assert popup.pdf_view.isVisible()
    assert not popup.status_label.isVisible()

    popup.close()
