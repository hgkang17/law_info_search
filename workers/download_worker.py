"""별표·서식 파일을 배경에서 내려받는다."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from utils.law_download import (
    download_law_file,
    download_law_pdf,
    download_ordinance_annex_pages,
    is_allowed_law_file_url,
    is_allowed_law_pdf_url,
)

__all__ = [
    "OrdinanceAnnexPreviewWorker",
    "PdfDownloadWorker",
    "download_law_file",
    "download_law_pdf",
    "download_ordinance_annex_pages",
    "is_allowed_law_file_url",
    "is_allowed_law_pdf_url",
]


class PdfDownloadWorker(QThread):
    """PDF 미리보기를 위해 원격 파일을 내려받는 작업 스레드."""

    succeeded = Signal(bytes)
    failed = Signal(str)

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        try:
            self.succeeded.emit(download_law_pdf(self.url))
        except Exception as exc:
            self.failed.emit(str(exc))


class OrdinanceAnnexPreviewWorker(QThread):
    """자치법규 HWP를 법제처가 변환한 쪽 이미지로 받는 작업 스레드."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, url: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.url = url

    def run(self) -> None:
        try:
            pages, total = download_ordinance_annex_pages(self.url)
            self.succeeded.emit({"pages": pages, "total": total})
        except Exception as exc:
            self.failed.emit(str(exc))
