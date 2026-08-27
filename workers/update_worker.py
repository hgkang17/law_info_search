"""업데이트 조회와 다운로드를 UI 스레드 밖에서 실행한다."""

from __future__ import annotations

from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal

from utils.updater import (
    ReleaseInfo,
    UpdateCancelled,
    UpdateError,
    download_release,
    fetch_latest_release,
)


class UpdateCheckWorker(QThread):
    resultReady = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            release = fetch_latest_release()
        except UpdateError as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
            return
        if not self.isInterruptionRequested():
            self.resultReady.emit(release)


class UpdateDownloadWorker(QThread):
    progressChanged = Signal(int, int)
    resultReady = Signal(str)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(
        self, release: ReleaseInfo, destination: Path, parent=None
    ) -> None:
        super().__init__(parent)
        self.release = release
        self.destination = Path(destination)
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()
        self.requestInterruption()

    def run(self) -> None:
        try:
            path = download_release(
                self.release,
                self.destination,
                progress=self.progressChanged.emit,
                cancelled=lambda: (
                    self._cancel_event.is_set()
                    or self.isInterruptionRequested()
                ),
            )
        except UpdateCancelled:
            self.cancelled.emit()
        except UpdateError as error:
            self.failed.emit(str(error))
        else:
            self.resultReady.emit(str(path))
