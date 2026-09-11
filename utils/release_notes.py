"""누적 업데이트 내역에서 특정 버전 또는 현재까지의 항목을 꺼낸다."""

from __future__ import annotations

from pathlib import Path
import re
import sys


_VERSION_HEADING = re.compile(
    r"(?m)^##\s+v?(\d+(?:\.\d+)*)\s*$", re.IGNORECASE
)


def display_version(value: str) -> str:
    """``v1.4.4``를 화면과 문서에서 쓰는 ``1.4.4``로 바꾼다."""
    version = str(value or "").strip()
    if version[:1].casefold() == "v":
        version = version[1:]
    return version or "새 버전"


def _version_parts(value: str) -> tuple[int, ...]:
    version = display_version(value)
    if not re.fullmatch(r"\d+(?:\.\d+)*", version):
        return ()
    return tuple(int(part) for part in version.split("."))


def _version_sections(notes: str) -> list[tuple[str, str]]:
    matches = list(_VERSION_HEADING.finditer(notes))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(notes)
        sections.append((match.group(1), notes[match.start():end].strip()))
    return sections


def release_notes_for_version(notes: str, version: str) -> str:
    """GitHub Release 본문으로 쓸 해당 버전 항목 하나를 반환한다."""
    target = display_version(version)
    return next(
        (section for item_version, section in _version_sections(notes) if item_version == target),
        "",
    )


def cumulative_notes_through(notes: str, version: str) -> str:
    """아직 배포되지 않은 미래 항목을 빼고 해당 버전까지 최신순으로 반환한다."""
    target = _version_parts(version)
    if not target:
        return ""
    selected = [
        section
        for item_version, section in _version_sections(notes)
        if (parts := _version_parts(item_version)) and parts <= target
    ]
    if not selected:
        return ""
    return "# 업데이트 내역\n\n" + "\n\n".join(selected)


def main(arguments: list[str] | None = None) -> int:
    """릴리스 워크플로에서 해당 버전 항목을 별도 Markdown으로 만든다."""
    values = list(sys.argv[1:] if arguments is None else arguments)
    if len(values) != 3:
        print("usage: release_notes SOURCE VERSION DESTINATION", file=sys.stderr)
        return 2
    source_text, version, destination_text = values
    source = Path(source_text)
    destination = Path(destination_text)
    try:
        notes = source.read_text(encoding="utf-8")
    except OSError as error:
        print(f"업데이트 내역 파일을 읽지 못했습니다: {error}", file=sys.stderr)
        return 1
    selected = release_notes_for_version(notes, version)
    if not selected:
        print(
            f"업데이트 내역에 {display_version(version)} 항목이 없습니다.",
            file=sys.stderr,
        )
        return 1
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(selected + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
