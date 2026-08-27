import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from storage.paths import CACHE_ROOT
from ui.about import AboutDialog, LicenseTextDialog
from ui.assets import LICENSE_DIR
from utils.constants import (
    APP_VERSION,
    AUTHOR_NAME,
    CONTACT_EMAIL,
    COPYRIGHT_YEAR,
)


def _dialog() -> AboutDialog:
    QApplication.instance() or QApplication([])
    return AboutDialog()


def test_about_shows_author_contact_and_version() -> None:
    dialog = _dialog()
    text = dialog.browser.toPlainText()
    assert AUTHOR_NAME in text
    assert CONTACT_EMAIL in text
    assert APP_VERSION in text


def test_copyright_line_names_the_author() -> None:
    # 연도만 있는 저작권 표시는 저작권자를 특정하지 못한다.
    dialog = _dialog()
    label = dialog.findChild(QLabel, "aboutCopyright")
    assert label is not None
    assert AUTHOR_NAME in label.text()
    assert COPYRIGHT_YEAR in label.text()
    assert "위에 밝힌 오픈소스는 각 라이선스를 따릅니다" in label.text()
    assert "프로그램 저작권은 제작자에게" not in label.text()


def test_about_declares_required_licenses() -> None:
    # 공개 소스와 재배포 조건이 붙은 구성 요소는 이름ㆍ라이선스가 화면에
    # 모두 드러나야 한다.
    dialog = _dialog()
    text = dialog.browser.toPlainText()
    assert "PySide6" in text
    assert "LGPL v3" in text
    assert "Pretendard" in text
    assert "SIL Open Font License 1.1" in text
    assert "kordoc" in text
    assert "korean-law-mcp" in text
    assert "MIT License" in text
    assert "UI 라이브러리" in text
    assert "사용폰트" in text
    assert "PDF/HWP 분석" in text
    assert "법령 AI 도구" in text
    assert "프로그램 소스" in text


def test_about_credits_law_open_api() -> None:
    dialog = _dialog()
    text = dialog.browser.toPlainText()
    assert "국가법령정보 공동활용" in text
    assert "법적 효력" in text


def test_license_copies_are_bundled() -> None:
    # 빌드 spec이 이 파일들을 번들에 넣는다. 파일이 사라지면 고지
    # 의무를 못 채우므로 저장소 단계에서 막는다.
    expected = {
        "LICENSE.LGPLv3.txt",
        "LICENSE.GPLv3.txt",
        "LICENSE.Pretendard-OFL.txt",
        "LICENSE.kordoc-MIT.txt",
        "LICENSE.korean-law-mcp-MIT.txt",
        "LICENSE.project-MIT.txt",
    }
    assert LICENSE_DIR.is_dir()
    present = {path.name for path in LICENSE_DIR.iterdir()}
    assert expected <= present


def test_license_button_is_available() -> None:
    dialog = _dialog()
    assert dialog.license_button.isEnabled()


def test_about_shows_save_location_and_backup_warning() -> None:
    # 캐시 폴더가 어디인지, 지워도 되는지를 알려 주지 않으면
    # 저장 위치를 열어 봐도 무엇을 지워야 하는지 모른다.
    dialog = _dialog()
    text = dialog.browser.toPlainText()
    assert str(CACHE_ROOT) in text
    assert "위 저장 위치" in text
    assert "삭제" in text
    assert dialog.cache_button.isEnabled()


def test_license_text_dialog_shows_real_license_text() -> None:
    # 실행 파일 하나로 배포하면 사본이 임시 폴더에 풀리므로, 파일 탐색기
    # 대신 이 창이 "쉽게 확인할 수 있는 형태"를 맡는다.
    QApplication.instance() or QApplication([])
    dialog = LicenseTextDialog()
    assert dialog.selector.count() == 6
    text = dialog.viewer.toPlainText()
    assert "GNU LESSER GENERAL PUBLIC LICENSE" in text

    dialog.selector.setCurrentIndex(2)
    font_text = dialog.viewer.toPlainText()
    assert "SIL OPEN FONT LICENSE" in font_text.upper()

    dialog.selector.setCurrentIndex(3)
    kordoc_text = dialog.viewer.toPlainText()
    assert "kordoc" in kordoc_text.lower() or "MIT License" in kordoc_text

    dialog.selector.setCurrentIndex(4)
    mcp_text = dialog.viewer.toPlainText()
    assert "korean-law-mcp" in mcp_text.lower()

    dialog.selector.setCurrentIndex(5)
    project_text = dialog.viewer.toPlainText()
    assert "Copyright (c) 2026 hgkang" in project_text


def test_qt_notice_does_not_claim_replaceable_dlls() -> None:
    # 실행 파일 하나로 묶으면 사용자가 Qt를 교체할 수 없다. 지키지 않는
    # 조건을 지킨다고 적으면 고지 자체가 거짓이 된다.
    dialog = _dialog()
    text = dialog.browser.toPlainText()
    assert "별도 파일로 동적 링크" not in text
    assert "요청" in text
