from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import requests

from utils.constants import UPDATE_ASSET_NAME
from utils.updater import (
    ReleaseInfo,
    UpdateError,
    consume_startup_option,
    download_release,
    fetch_latest_release,
    install_staged_executable,
    is_newer_version,
    version_parts,
)


class FakeResponse:
    def __init__(
        self,
        *,
        payload=None,
        content: bytes = b"",
        chunks: list[bytes] | None = None,
        status_code: int = 200,
    ) -> None:
        self.payload = payload
        self.content = content
        self.chunks = chunks if chunks is not None else [content]
        self.status_code = status_code
        self.headers: dict[str, str] = {}

    def json(self):
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)

    def iter_content(self, chunk_size: int):
        del chunk_size
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def _release(data: bytes) -> ReleaseInfo:
    return ReleaseInfo(
        version="2.2.0",
        tag_name="v2.2.0",
        name="v2.2.0",
        notes="변경 내용",
        page_url="https://github.com/hgkang17/law_info_search/releases/tag/v2.2.0",
        download_url=(
            "https://github.com/hgkang17/law_info_search/releases/download/"
            f"v2.2.0/{UPDATE_ASSET_NAME}"
        ),
        asset_name=UPDATE_ASSET_NAME,
        asset_size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
    )


def test_version_comparison_accepts_v_prefix_and_trailing_zeroes() -> None:
    assert version_parts("v2.1.0") == (2, 1)
    assert is_newer_version("v2.1.1", "2.1.0")
    assert not is_newer_version("2.1.0", "2.1")
    with pytest.raises(UpdateError):
        version_parts("release-two")


def test_fetch_latest_release_requires_matching_exe_and_checksum() -> None:
    data = b"new executable"
    checksum = hashlib.sha256(data).hexdigest()
    payload = {
        "tag_name": "v2.2.0",
        "name": "정식 2.2.0",
        "body": "수정 사항",
        "html_url": "https://github.com/hgkang17/law_info_search/releases/tag/v2.2.0",
        "assets": [
            {
                "name": UPDATE_ASSET_NAME,
                "size": len(data),
                "browser_download_url": (
                    "https://github.com/hgkang17/law_info_search/releases/download/"
                    f"v2.2.0/{UPDATE_ASSET_NAME}"
                ),
            },
            {
                "name": f"{UPDATE_ASSET_NAME}.sha256",
                "size": 90,
                "browser_download_url": (
                    "https://github.com/hgkang17/law_info_search/releases/download/"
                    f"v2.2.0/{UPDATE_ASSET_NAME}.sha256"
                ),
            },
        ],
    }
    session = FakeSession(
        [
            FakeResponse(payload=payload),
            FakeResponse(content=f"{checksum}  {UPDATE_ASSET_NAME}\n".encode()),
        ]
    )

    result = fetch_latest_release(session=session)

    assert result.version == "2.2.0"
    assert result.sha256 == checksum
    assert result.asset_size == len(data)
    assert len(session.calls) == 2
    assert session.calls[0][1]["headers"]["X-GitHub-Api-Version"]
    session.calls[0][1]["headers"]["User-Agent"].encode("ascii")


def test_fetch_latest_release_rejects_missing_checksum() -> None:
    payload = {
        "tag_name": "v2.2.0",
        "assets": [
            {
                "name": UPDATE_ASSET_NAME,
                "size": 10,
                "browser_download_url": (
                    "https://github.com/hgkang17/law_info_search/releases/download/"
                    f"v2.2.0/{UPDATE_ASSET_NAME}"
                ),
            }
        ],
    }
    with pytest.raises(UpdateError, match="검증 파일"):
        fetch_latest_release(session=FakeSession([FakeResponse(payload=payload)]))


def test_fetch_latest_release_rejects_non_github_asset_url() -> None:
    payload = {
        "tag_name": "v2.2.0",
        "assets": [
            {
                "name": UPDATE_ASSET_NAME,
                "size": 10,
                "browser_download_url": "https://example.com/update.exe",
            }
        ],
    }
    with pytest.raises(UpdateError, match="GitHub가 아닌"):
        fetch_latest_release(session=FakeSession([FakeResponse(payload=payload)]))


def test_download_release_verifies_and_atomically_finishes(tmp_path: Path) -> None:
    data = b"abcdef" * 500
    destination = tmp_path / "update.exe"
    progress: list[tuple[int, int]] = []

    result = download_release(
        _release(data),
        destination,
        session=FakeSession(
            [FakeResponse(content=data, chunks=[data[:1000], data[1000:]])]
        ),
        progress=lambda received, total: progress.append((received, total)),
    )

    assert result == destination
    assert destination.read_bytes() == data
    assert not (tmp_path / "update.exe.part").exists()
    assert progress[-1] == (len(data), len(data))


def test_download_release_keeps_existing_file_on_hash_failure(
    tmp_path: Path,
) -> None:
    data = b"tampered"
    destination = tmp_path / "update.exe"
    destination.write_bytes(b"previous verified file")
    original = _release(data)
    release = ReleaseInfo(**{**original.__dict__, "sha256": "0" * 64})

    with pytest.raises(UpdateError, match="SHA-256"):
        download_release(
            release,
            destination,
            session=FakeSession([FakeResponse(content=data)]),
        )

    assert destination.read_bytes() == b"previous verified file"
    assert not (tmp_path / "update.exe.part").exists()


def test_install_staged_executable_replaces_target(tmp_path: Path) -> None:
    source = tmp_path / "staged.exe"
    target = tmp_path / "installed.exe"
    source.write_bytes(b"new")
    target.write_bytes(b"old")

    expected = hashlib.sha256(b"new").hexdigest()
    install_staged_executable(source, target, expected)

    assert source.read_bytes() == b"new"
    assert target.read_bytes() == b"new"


def test_install_staged_executable_rejects_last_moment_tampering(
    tmp_path: Path,
) -> None:
    source = tmp_path / "staged.exe"
    target = tmp_path / "installed.exe"
    source.write_bytes(b"tampered")
    target.write_bytes(b"old")

    with pytest.raises(UpdateError, match="교체 직전"):
        install_staged_executable(source, target, "0" * 64)

    assert target.read_bytes() == b"old"


def test_consume_startup_option_removes_internal_arguments() -> None:
    arguments = ["program.exe", "--updated-version", "v2.2.0", "user-arg"]
    assert consume_startup_option(arguments, "--updated-version") == "v2.2.0"
    assert arguments == ["program.exe", "user-arg"]


def test_release_workflow_builds_required_assets() -> None:
    workflow = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "국가법령정보 통합검색.spec" in workflow
    assert UPDATE_ASSET_NAME in workflow
    assert f"{UPDATE_ASSET_NAME}.sha256" in workflow
    assert "--generate-notes" in workflow
