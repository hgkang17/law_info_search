"""EXE를 바꿀 수 없는 자리에서 업데이트가 안내를 제대로 하는지 검증."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from utils.updater import (
    UpdateError,
    _is_protected_location,
    executable_location_is_writable,
    install_location_hint,
    install_staged_executable,
)


@pytest.mark.parametrize(
    "path",
    [
        r"C:\국가법령정보 통합검색.exe",
        r"C:\Program Files\법령\app.exe",
        r"C:\Program Files (x86)\법령\app.exe",
        r"C:\Windows\System32\app.exe",
        r"C:\ProgramData\법령\app.exe",
    ],
)
def test_admin_only_folders_are_recognized(path: str) -> None:
    assert _is_protected_location(Path(path))


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\User\Desktop\app.exe",
        r"C:\Users\User\Documents\법령\app.exe",
        r"D:\작업\법령\app.exe",
    ],
)
def test_ordinary_folders_are_not_flagged(path: str) -> None:
    assert not _is_protected_location(Path(path))


def test_hint_tells_protected_folders_to_move_the_program() -> None:
    hint = install_location_hint(Path(r"C:\Program Files\법령\app.exe"))

    assert "관리자 권한" in hint
    assert "바탕화면" in hint


def test_hint_for_other_folders_points_at_locks_and_space() -> None:
    hint = install_location_hint(Path(r"D:\작업\법령\app.exe"))

    assert "백신" in hint
    assert "여유 공간" in hint


def test_replacement_failure_names_the_file_and_the_reason(tmp_path) -> None:
    """도우미가 넘길 사유 한 줄에 경로와 운영체제 오류가 함께 담긴다."""
    source = tmp_path / "new.exe"
    source.write_bytes(b"new")
    target = tmp_path / "old.exe"
    target.write_bytes(b"old")

    # 교체 직전 단계에서 실패하도록 대상 자리를 폴더로 막아 둔다.
    blocker = target.with_name(f".{target.name}.update-new.exe")
    blocker.mkdir()

    with pytest.raises(UpdateError) as caught:
        install_staged_executable(source, target)

    message = str(caught.value)
    assert "기존 실행 파일을 교체하지 못했습니다" in message
    assert str(target) in message
    # 명령줄 인자로 넘어가므로 줄바꿈이 섞이면 안 된다.
    assert "\n" not in message

    # 실패해도 원래 파일은 그대로 남는다.
    assert target.read_bytes() == b"old"


def test_writability_probe_leaves_nothing_behind(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("utils.updater.sys.executable", str(tmp_path / "app.exe"))
    monkeypatch.setattr("utils.updater.can_self_update", lambda: True)

    before = set(os.listdir(tmp_path))
    assert executable_location_is_writable()

    assert set(os.listdir(tmp_path)) == before
