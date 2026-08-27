"""국가법령정보 통합검색 실행 진입점."""

from __future__ import annotations

import sys


def main() -> int:
    # 내려받은 새 onefile EXE가 기존 EXE의 종료를 기다렸다 교체하는 모드다.
    # Qt를 불러오기 전에 처리해야 도우미가 작고 빠르게 끝난다.
    if "--apply-update" in sys.argv[1:]:
        from utils.updater import apply_update_mode

        index = sys.argv.index("--apply-update")
        values = sys.argv[index + 1 : index + 5]
        if len(values) != 4:
            return 2
        return apply_update_mode(*values)

    # PyInstaller onefile에서도 같은 exe를 stdio MCP 서버로 다시 띄울 수
    # 있게 한다. Qt를 임포트하기 전에 갈라야 서버 시작이 빠르고 GUI 초기화도
    # 일어나지 않는다.
    if "--mcp-server" in sys.argv[1:]:
        from mcp_server.server import mcp

        mcp.run()
        return 0

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from storage.paths import ensure_cache_dirs, migrate_legacy_cache_dirs
    from ui.assets import LOGO_PATH
    from ui.main_window import LawSearchWindow
    from ui.theme import register_bundled_pretendard_fonts
    from utils.constants import APP_VERSION, FONT_FAMILY
    from utils.updater import cleanup_staged_executable, consume_startup_option

    # 내부 옵션은 Qt가 해석하지 않도록 QApplication 생성 전에 제거한다.
    startup_arguments = sys.argv[:]
    updated_version = consume_startup_option(
        startup_arguments, "--updated-version"
    )
    cleanup_source = consume_startup_option(
        startup_arguments, "--cleanup-update-source"
    )
    update_error = consume_startup_option(startup_arguments, "--update-error")
    sys.argv = startup_arguments

    # 저장 자료를 읽는 화면이 뜨기 전에 옛 폴더를 지금 자리로 옮긴다.
    migrate_legacy_cache_dirs()
    ensure_cache_dirs()
    app = QApplication(sys.argv)
    register_bundled_pretendard_fonts()
    app.setApplicationName("국가법령정보 통합검색")
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.Normal))
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    window = LawSearchWindow()
    window.show()
    if cleanup_source:
        cleanup_attempts = {"remaining": 30}

        def cleanup_update_source() -> None:
            if cleanup_staged_executable(cleanup_source):
                return
            cleanup_attempts["remaining"] -= 1
            if cleanup_attempts["remaining"] > 0:
                QTimer.singleShot(500, cleanup_update_source)

        QTimer.singleShot(500, cleanup_update_source)
    if updated_version:
        QTimer.singleShot(
            700,
            lambda: QMessageBox.information(
                window,
                "업데이트 완료",
                f"{updated_version} 버전으로 업데이트했습니다.",
            ),
        )
    elif update_error:
        QTimer.singleShot(
            500,
            lambda: QMessageBox.critical(window, "업데이트 실패", update_error),
        )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
