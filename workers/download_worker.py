"""별표·서식 파일을 배경에서 내려받는다."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal

from utils.law_download import (
    download_law_file,
    download_law_pdf,
    download_ordinance_annex_pages,
    is_allowed_law_file_url,
    is_allowed_law_pdf_url,
    save_law_file,
)
from utils.law_site_download import download_official_law_document

__all__ = [
    "AnnexFileDownloadWorker",
    "OrdinanceAnnexPreviewWorker",
    "PdfDownloadWorker",
    "LawHwpxDownloadWorker",
    "LawDocumentDownloadWorker",
    "download_law_file",
    "download_law_pdf",
    "download_ordinance_annex_pages",
    "is_allowed_law_file_url",
    "is_allowed_law_pdf_url",
    "save_law_file",
]


class AnnexFileDownloadWorker(QThread):
    """별표ㆍ서식 원본을 브라우저 없이 받아 정해진 폴더에 저장한다.

    본문의 원본ㆍPDF 링크를 누르면 지금까지는 기본 브라우저가 떴다.
    받은 파일이 프로그램 밖으로 나가 버려, 머리글의 다운로드 목록에도
    잡히지 않았다. 전문 다운로드와 같은 자리에 쌓이도록 여기서 받는다.
    """

    progress = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(
        self, url: str, destination: str, suggested_name: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.url = url
        self.destination = destination
        self.suggested_name = suggested_name

    def run(self) -> None:
        try:
            saved = save_law_file(
                self.url,
                self.destination,
                suggested_name=self.suggested_name,
                progress=self.progress.emit,
            )
            self.succeeded.emit(str(saved))
        except Exception as exc:  # noqa: BLE001 - 실패 사유를 그대로 보여 준다
            self.failed.emit(str(exc))


class LawDocumentDownloadWorker(QThread):
    """사이트 브라우저와 선택된 저장 경로를 UI 스레드 밖에서 처리한다.

    법령·행정규칙·자치법규를 ``kind``로 구분한다. 세 종류 모두 국가법령
    정보센터 저장 창의 기본값인 HWP(HWPML)로 받는다.
    """

    progress = Signal(str)
    succeeded = Signal(str)
    failed = Signal(str)

    def __init__(
        self, kind: str, item_id: str, title: str, effective_date: str,
        destination: str, parent: QObject | None = None, *,
        articles: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.kind = kind
        self.item_id = item_id
        self.title = title
        self.effective_date = effective_date
        self.destination = destination
        # 고른 조문(6자리 조 번호). 비어 있으면 전문을 받는다.
        self.articles = list(articles or [])

    def run(self) -> None:
        try:
            saved = download_official_law_document(
                self.kind, self.item_id, self.title, self.effective_date,
                self.destination, self.progress.emit,
                self.articles or None,
            )
            self.succeeded.emit(str(saved))
        except Exception as exc:
            self.failed.emit(str(exc))


# 예전 이름으로 부르던 코드를 위해 남겨 둔다.
LawHwpxDownloadWorker = LawDocumentDownloadWorker


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
