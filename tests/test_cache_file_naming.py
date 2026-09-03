"""저장 파일ㆍ목록 캐시 이름을 제목 기준으로 바꾼 뒤의 검증."""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from storage.cache import LawDocumentCache, SearchResultCache

LAW_ROW = {
    "target": "law",
    "label": "법령",
    "id": "009419",
    "name": "국토의 계획 및 이용에 관한 법률 시행령",
}
ARTICLE_ROW = {
    "target": "ai_related",
    "id": "009293",
    "name": "국토기본법",
    "provision": "제6조 국토계획의 정의 및 구분",
    "jo_code": "000600",
}


def test_saved_file_name_starts_with_the_title(tmp_path) -> None:
    """파일 이름만 봐도 무엇을 저장한 것인지 알 수 있다."""
    cache = LawDocumentCache(tmp_path / "저장내역")
    assert cache.path_for_row(LAW_ROW).name == (
        "국토의 계획 및 이용에 관한 법률 시행령_law_009419.json"
    )
    assert cache.path_for_row(ARTICLE_ROW).name == (
        "국토기본법 제6조 국토계획의 정의 및 구분_ai_related_009293_000600.json"
    )


def test_same_title_with_different_id_stays_separate(tmp_path) -> None:
    """이름이 같아도 다른 자료면 서로 덮어쓰지 않는다."""
    cache = LawDocumentCache(tmp_path / "저장내역")
    other = dict(LAW_ROW, id="009420")
    assert cache.path_for_row(LAW_ROW) != cache.path_for_row(other)

    # 분류가 다른 같은 이름도 마찬가지다.
    ordinance = dict(LAW_ROW, target="ordin")
    assert cache.path_for_row(LAW_ROW) != cache.path_for_row(ordinance)


def test_long_titles_are_cut_but_stay_unique(tmp_path) -> None:
    """제목이 아주 길어도 경로 상한에 걸리지 않고 서로 구분된다."""
    cache = LawDocumentCache(tmp_path / "저장내역")
    first = dict(LAW_ROW, name="가" * 200, id="1")
    second = dict(LAW_ROW, name="가" * 200, id="2")
    assert len(cache.path_for_row(first).stem) < 120
    assert cache.path_for_row(first) != cache.path_for_row(second)


def test_old_number_only_files_are_renamed_once(tmp_path) -> None:
    """번호만 있던 예전 파일을 지우지 않고 새 이름으로 옮긴다."""
    directory = tmp_path / "저장내역"
    directory.mkdir(parents=True)
    legacy = directory / "law_009419.json"
    legacy.write_text(
        json.dumps(
            {
                "schema": 1,
                "key": "law_009419",
                "row": LAW_ROW,
                "메모": "사용자가 붙인 메모",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cache = LawDocumentCache(directory)
    moved = directory / "국토의 계획 및 이용에 관한 법률 시행령_law_009419.json"
    assert not legacy.exists()
    assert moved.exists()

    record = json.loads(moved.read_text(encoding="utf-8"))
    assert record["메모"] == "사용자가 붙인 메모"
    assert record["key"] == "국토의 계획 및 이용에 관한 법률 시행령_law_009419"
    assert cache.has(LAW_ROW)

    # 표식이 남아 두 번 돌지 않는다.
    assert (directory / LawDocumentCache.NAMING_MARKER).is_file()
    assert LawDocumentCache(directory).migrate_to_named_files() == 0


def test_migration_keeps_both_files_on_name_clash(tmp_path) -> None:
    """새 이름이 이미 있으면 옛 파일을 지우지 않고 그대로 둔다."""
    directory = tmp_path / "저장내역"
    directory.mkdir(parents=True)
    payload = json.dumps({"schema": 1, "row": LAW_ROW}, ensure_ascii=False)
    legacy = directory / "law_009419.json"
    legacy.write_text(payload, encoding="utf-8")
    (directory / "국토의 계획 및 이용에 관한 법률 시행령_law_009419.json").write_text(
        payload, encoding="utf-8"
    )

    LawDocumentCache(directory)
    assert legacy.exists()


def test_search_list_cache_keeps_the_query_in_the_name(tmp_path) -> None:
    """목록 캐시도 검색어를 이름에 그대로 남긴다."""
    cache = SearchResultCache(tmp_path / "검색목록")
    assert cache.path_for("admrul", "주차장 설치", 1).name == (
        "admrul_1_주차장 설치.json"
    )
    # 범위가 다르면 다른 파일이다.
    assert cache.path_for("law", "주차장", 1) != cache.path_for("law", "주차장", 2)


def test_search_list_cache_survives_a_name_clash(tmp_path) -> None:
    """잘린 이름이 겹쳐도 저장된 검색어를 확인해 잘못 쓰지 않는다."""
    cache = SearchResultCache(tmp_path / "검색목록")
    long_query = "가" * 100
    other_query = "가" * 99 + "나"
    assert cache.path_for("law", long_query, 1) == cache.path_for(
        "law", other_query, 1
    )
    assert cache.save("law", long_query, 1, {"LawSearch": {}})
    assert cache.load("law", long_query, 1) is not None
    assert cache.load("law", other_query, 1) is None


def test_old_hashed_list_cache_is_renamed(tmp_path) -> None:
    """해시 이름으로 남아 있던 목록 캐시를 검색어 이름으로 옮긴다."""
    directory = tmp_path / "검색목록"
    directory.mkdir(parents=True)
    (directory / "admrul_1_5f95aba969f4b281cdee.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "target": "admrul",
                "query": "주차장",
                "search_scope": 1,
                "payload": {"AdmRulSearch": {}},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cache = SearchResultCache(directory)
    assert (directory / "admrul_1_주차장.json").is_file()
    assert cache.load("admrul", "주차장", 1) is not None
