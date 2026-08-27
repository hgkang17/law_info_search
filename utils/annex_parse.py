"""별표 첨부 파일을 kordoc로 Markdown으로 바꾼다.

kordoc은 Node 패키지라 Python에서 다시 구현하지 않고,
저장소의 kordoc_parser(한 번 npm install 한 로컬 복사본)를 부른다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

def _parser_dir() -> Path:
    """kordoc_parser 폴더 자리. 소스로 돌 때와 exe로 돌 때가 다르다.

    kordoc은 node_modules까지 딸린 Node 패키지라 exe 안에 넣지 않는다.
    exe로 묶으면 __file__은 임시 해제 폴더를 가리키므로 거기에는 없고,
    exe 옆에 폴더를 두면 쓸 수 있게 그 자리도 함께 본다.
    """
    candidates = [Path(__file__).resolve().parent.parent / "kordoc_parser"]
    if getattr(sys, "frozen", False):
        candidates.insert(
            0, Path(sys.executable).resolve().parent / "kordoc_parser"
        )
    for candidate in candidates:
        if (candidate / "parse.mjs").is_file():
            return candidate
    return candidates[0]


_PARSER_DIR = _parser_dir()
_PARSER_SCRIPT = _PARSER_DIR / "parse.mjs"
_KORDOC_PACKAGE = _PARSER_DIR / "node_modules" / "kordoc"
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

DOWNLOAD_NOTICE = re.compile(r"자세한\s*내용은[\s\S]{0,120}?(?:다운로드|주소창)")
_DOWNLOAD_NOTICE_ALL = re.compile(DOWNLOAD_NOTICE.pattern, re.MULTILINE)
_SUBSTANTIVE_MIN_CHARS = 150


class AnnexParseResult:
    __slots__ = ("success", "markdown", "file_type", "is_image_based", "page_count", "error")

    def __init__(
        self,
        *,
        success: bool,
        markdown: str = "",
        file_type: str = "",
        is_image_based: bool = False,
        page_count: int = 0,
        error: str = "",
    ) -> None:
        self.success = success
        self.markdown = markdown
        self.file_type = file_type
        self.is_image_based = is_image_based
        self.page_count = page_count
        self.error = error


def kordoc_ready() -> bool:
    return _PARSER_SCRIPT.is_file() and _KORDOC_PACKAGE.is_dir()


def kordoc_missing_message() -> str:
    return (
        "별표 원문 파서(kordoc)가 이 컴퓨터에 없습니다. "
        "프로젝트의 kordoc_parser 폴더에서 `npm install`을 한 뒤 "
        "다시 시도하세요."
    )


def is_download_notice_only(markdown: str) -> bool:
    """파일에 본문이 없고 다운로드 안내만 있는 별표를 가린다."""
    if not DOWNLOAD_NOTICE.search(markdown):
        return False
    substantive = _DOWNLOAD_NOTICE_ALL.sub(" ", markdown)
    substantive = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", substantive)
    substantive = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", substantive)
    substantive = re.sub(r"https?:\/\/\S+", " ", substantive)
    substantive = re.sub(r"</?[a-zA-Z][^>]*>", " ", substantive)
    substantive = re.sub(r"[■\[\]\\]", " ", substantive)
    substantive = re.sub(r"\s+", " ", substantive).strip()
    return len(substantive) < _SUBSTANTIVE_MIN_CHARS


def parse_annex_bytes(data: bytes) -> AnnexParseResult:
    """첨부 파일 바이트를 Markdown으로 바꾼다."""
    if not data:
        return AnnexParseResult(success=False, error="빈 파일입니다.")
    if not kordoc_ready():
        return AnnexParseResult(success=False, error=kordoc_missing_message())
    node = shutil.which("node")
    if not node:
        return AnnexParseResult(
            success=False,
            error="Node.js를 찾지 못했습니다. kordoc 파서를 쓰려면 node가 PATH에 있어야 합니다.",
        )
    try:
        completed = subprocess.run(
            [node, str(_PARSER_SCRIPT)],
            input=data,
            capture_output=True,
            timeout=90,
            cwd=str(_PARSER_DIR),
            creationflags=_CREATE_NO_WINDOW,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return AnnexParseResult(success=False, error=str(error))
    raw = completed.stdout.decode("utf-8", errors="replace").strip()
    if not raw:
        err = completed.stderr.decode("utf-8", errors="replace").strip()
        return AnnexParseResult(
            success=False,
            error=err or f"kordoc 종료 코드 {completed.returncode}",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return AnnexParseResult(success=False, error="kordoc 응답이 JSON이 아닙니다.")
    return AnnexParseResult(
        success=bool(payload.get("success")),
        markdown=str(payload.get("markdown") or ""),
        file_type=str(payload.get("fileType") or ""),
        is_image_based=bool(payload.get("isImageBased")),
        page_count=int(payload.get("pageCount") or 0),
        error=str(payload.get("error") or ""),
    )
