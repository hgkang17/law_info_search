"""법령 본문을 한글 문서로 내보낸다.

법제처 OPEN API는 별표ㆍ서식만 원본 HWP를 주고 법령 전문은 주지 않는다.
그래서 화면에 그린 본문을 우리가 직접 한글 문서로 만들어 준다.

만드는 형식은 **HWPX**다. 한글의 이진 형식(.hwp)은 OLE 복합 문서 안에
압축한 레코드를 넣는 구조라 순수 파이썬으로 안정적으로 만들기 어렵다.
HWPX는 한글 2010부터 쓰는 개방 형식(OWPML, KS X 6101)이고 ZIP+XML이라
프로그램이 만들 수 있으며, 한글에서 그대로 열고 다시 ``.hwp``로 저장할 수
있다.

본문 평문은 이미 조문 단위로 줄이 나뉘어 있다. 여기서는 그 줄을 문단으로
옮기면서 편ㆍ장ㆍ절과 조 제목만 제목 문단으로 올린다. 색상ㆍ메모 같은
화면 서식은 옮기지 않는다(1단계 범위).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


# 본문 평문에서 제목으로 올릴 줄.
_SECTION_PATTERN = re.compile(r"^\[([^\]\r\n]+)\]$")
_DIVISION_PATTERN = re.compile(r"^제\s*\d+\s*[편장절관](?:의\s*\d+)?(?:\s|$)")
# 파일 이름에 쓸 수 없는 글자.
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\r\n\t]+')


@dataclass(frozen=True)
class ExportBlock:
    """내보낼 문단 하나. ``level`` 0은 본문, 1ㆍ2는 제목."""

    text: str
    level: int = 0


def law_export_blocks(plain_text: str) -> list[ExportBlock]:
    """본문 평문을 문단 목록으로 나눈다.

    ``[조문]``ㆍ``[부칙]``처럼 대괄호로만 이뤄진 줄은 구간 제목,
    ``제3장 …``은 그 아래 제목으로 올린다. 조문은 제목으로 올리지 않는다.
    평문에서 조 제목과 조문 내용이 한 줄이라(``제1조(목적) 이 법은 …``)
    통째로 제목이 되면 문서 개요가 본문으로 가득 찬다.
    """
    blocks: list[ExportBlock] = []
    for raw_line in str(plain_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        section = _SECTION_PATTERN.match(line)
        if section is not None:
            blocks.append(ExportBlock(section.group(1).strip(), 1))
            continue
        if _DIVISION_PATTERN.match(line):
            blocks.append(ExportBlock(line, 2))
            continue
        blocks.append(ExportBlock(line, 0))
    return blocks


def default_export_name(title: str, suffix: str = ".hwpx") -> str:
    """저장 대화상자에 미리 넣어 둘 파일 이름."""
    cleaned = _UNSAFE_NAME.sub(" ", str(title or "")).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)[:80].strip()
    return f"{cleaned or '법령'}{suffix}"


def save_law_hwpx(
    path: str | Path,
    title: str,
    headline: str,
    plain_text: str,
) -> Path:
    """법령 본문을 HWPX 파일로 저장하고 그 경로를 돌려준다.

    ``headline``은 ``[시행 2026. 7. 1.] [법률 제21447호 …]``처럼 제목 아래
    한 줄로 붙는 법제처식 머리글이다.
    """
    try:
        from hwpx import HwpxDocument
    except ImportError as exc:  # pragma: no cover - 설치 누락은 실행 중에만
        raise RuntimeError(
            "한글 문서 저장에 필요한 hwpx 모듈을 불러오지 못했습니다."
        ) from exc

    target = Path(path)
    document = HwpxDocument.new()
    document.add_heading(str(title or "법령"), level=1)
    if headline:
        document.add_paragraph(str(headline))
    for block in law_export_blocks(plain_text):
        if block.level:
            # 제목 단계는 문서 안에서 편ㆍ장(1)과 조(2)만 구분한다.
            document.add_heading(block.text, level=min(block.level + 1, 3))
        else:
            document.add_paragraph(block.text)
    document.save_to_path(str(target))
    return target
