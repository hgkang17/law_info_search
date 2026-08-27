"""별표 번호 표기와 원문 파서."""

from __future__ import annotations

from utils.annex_notation import (
    annex_hint_in_query,
    annex_related_law_name,
    from_annex_code,
    row_matches_annex_hint,
    to_annex_code,
)
from utils.annex_parse import AnnexParseResult, is_download_notice_only, parse_annex_bytes


def test_annex_code_roundtrip() -> None:
    assert to_annex_code(28) == "002800"
    assert to_annex_code(17, 12) == "001712"
    assert from_annex_code("002003") == (20, 3)


def test_annex_related_law_name_reads_title_before_annex() -> None:
    assert annex_related_law_name("건축법 시행령 별표 1") == "건축법 시행령"
    assert annex_related_law_name("별표 1") == ""
    assert annex_related_law_name("별지 제1호서식") == ""


def test_annex_hint_reads_branch_number() -> None:
    assert annex_hint_in_query("관세법 별표 1의2") == "000102"
    assert annex_hint_in_query("여권법 별지 제3호서식") == "3"


def test_row_matches_annex_hint() -> None:
    row = {"별표번호": "000400"}
    assert row_matches_annex_hint(row, "4")
    assert not row_matches_annex_hint(row, "5")


def test_download_notice_only_needs_both_conditions() -> None:
    notice = (
        "자세한 내용은 아래 파일을 다운로드하시기 바랍니다. "
        "https://www.law.go.kr/file.hwp"
    )
    assert is_download_notice_only(notice)
    mixed = notice + "가. 과세표준은 다음 각 호와 같다. " * 20
    assert not is_download_notice_only(mixed)
    assert not is_download_notice_only("별표 1 수수료 1,000원")


def test_parse_annex_bytes_reports_missing_helper(
    monkeypatch,
) -> None:
    monkeypatch.setattr("utils.annex_parse.kordoc_ready", lambda: False)
    result = parse_annex_bytes(b"%PDF-1.4")
    assert result.success is False
    assert "kordoc" in result.error


def test_annex_parse_result_slots() -> None:
    result = AnnexParseResult(success=True, markdown="# 표", file_type="hwpx")
    assert result.markdown.startswith("#")
