from __future__ import annotations

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QSettings

from ui.main_window import LawSearchWindow
from utils.formatting import full_law_url
from workers.download_worker import is_allowed_law_pdf_url


def test_api_key_is_stored_as_plain_text(tmp_path) -> None:
    settings = QSettings(
        str(tmp_path / "api-key.ini"), QSettings.Format.IniFormat
    )
    host = SimpleNamespace(settings=settings)

    LawSearchWindow._store_api_key(host, "test-secret-value")

    assert settings.value("oc_key") == "test-secret-value"
    assert not settings.contains("oc_key_protected")
    assert LawSearchWindow._load_saved_api_key(host) == "test-secret-value"


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://www.law.go.kr/file.pdf", True),
        ("https://law.go.kr/file.pdf", True),
        ("https://open.law.go.kr/file.pdf", True),
        ("http://www.law.go.kr/file.pdf", False),
        ("https://law.go.kr.evil.example/file.pdf", False),
        ("https://evil.example/?next=https://law.go.kr/file.pdf", False),
        ("https://user@law.go.kr/file.pdf", False),
    ],
)
def test_pdf_url_allowlist(url: str, allowed: bool) -> None:
    assert is_allowed_law_pdf_url(url) is allowed


def test_official_legacy_http_pdf_url_is_upgraded_to_https() -> None:
    assert full_law_url("http://www.law.go.kr/file.pdf") == (
        "https://www.law.go.kr/file.pdf"
    )
