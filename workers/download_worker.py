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
from utils.law_site_download import download_official_law_hwpx

__all__ = [
    "OrdinanceAnnexPreviewWorker",
    "PdfDownloadWorker",
    "LawHwpxDownloadWorker",
    "download_law_file",
    "download_law_pdf",
    "download_ordinance_annex_pages",
    "is_allowed_law_file_url",
    "is_allowed_law_pdf_url",
]


class LawHwpxDownloadWorker(QThread):
    """사이트 브라우저와 선택된 저장 경로를 UI 스레드 밖에서 처리한다."""

    progress = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(
        self, law_id: str, title: str, effective_date: str, destination: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.law_id = law_id
        self.title = title
        self.effective_date = effective_date
        self.destination = destination

    def run(self) -> None:
        try:
            saved = download_official_law_hwpx(
                self.law_id, self.title, self.effective_date, self.destination,
                self.progress.emit,
            )
            self.succeeded.emit(str(saved))
        except Exception as exc:
            self.failed.emit(str(exc))


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
