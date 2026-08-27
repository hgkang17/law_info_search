import importlib
import sys

import pytest


def _paths_module(tmp_path, monkeypatch):
    """RUNTIME_DIR을 임시 폴더로 돌린 storage.paths를 새로 불러온다."""
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    sys.modules.pop("storage.paths", None)
    module = importlib.import_module("storage.paths")
    monkeypatch.setattr(module, "RUNTIME_DIR", tmp_path)
    root = tmp_path / "# law 캐시"
    monkeypatch.setattr(module, "CACHE_ROOT", root)
    law = root / "저장내역"
    reference = root / "조문"
    search = root / "검색목록"
    monkeypatch.setattr(module, "LAW_CACHE_DIR", law)
    monkeypatch.setattr(module, "LAW_REFERENCE_CACHE_DIR", reference)
    monkeypatch.setattr(module, "SEARCH_RESULT_CACHE_DIR", search)
    monkeypatch.setattr(
        module,
        "_LEGACY_CACHE_DIRS",
        (
            (tmp_path / "저장된_법령", law),
            (tmp_path / "조문_캐시", reference),
            (tmp_path / "검색목록_캐시", search),
            (tmp_path / "# law 캐시_저장내역", law),
            (tmp_path / "# law 캐시_조문", reference),
            (tmp_path / "# law 캐시_검색목록", search),
        ),
    )
    return module, law, reference, search


def test_cache_dirs_live_under_one_folder() -> None:
    # 새로 불러온 실제 모듈로 확인한다(임시 경로 패치 없이).
    sys.modules.pop("storage.paths", None)
    module = importlib.import_module("storage.paths")
    assert module.LAW_CACHE_DIR.parent == module.CACHE_ROOT
    assert module.LAW_REFERENCE_CACHE_DIR.parent == module.CACHE_ROOT
    assert module.SEARCH_RESULT_CACHE_DIR.parent == module.CACHE_ROOT
    assert module.CACHE_ROOT.name == "# law 캐시"


def test_cache_root_is_fixed_under_localappdata() -> None:
    # exe를 어디에 두든 저장 자리는 하나여야 한다. exe 옆에 두면 옮길
    # 때마다 빈 폴더가 새로 생겨 메모ㆍ즐겨찾기가 사라진 것처럼 보인다.
    sys.modules.pop("storage.paths", None)
    module = importlib.import_module("storage.paths")
    assert module.CACHE_ROOT.parent == module.APPDATA_CACHE_PARENT
    assert module.CACHE_ROOT != module.PORTABLE_CACHE_ROOT
    assert "AppData" in str(module.CACHE_ROOT)


def test_moves_cache_left_beside_exe_by_older_build(
    tmp_path, monkeypatch
) -> None:
    # 예전 판은 exe 옆에 저장했다. 거기 남은 메모ㆍ즐겨찾기를 가져와야 한다.
    module, law, _, _ = _paths_module(tmp_path, monkeypatch)
    portable = tmp_path / "예전자리" / "# law 캐시"
    (portable / "저장내역").mkdir(parents=True)
    (portable / "저장내역" / "law_1.json").write_text(
        '{"memos": ["직접 쓴 메모"]}', encoding="utf-8"
    )
    monkeypatch.setattr(module, "PORTABLE_CACHE_ROOT", portable)

    module.migrate_legacy_cache_dirs()

    assert "직접 쓴 메모" in (law / "law_1.json").read_text(encoding="utf-8")
    assert not portable.exists()


def test_moves_previous_generation_dirs(tmp_path, monkeypatch) -> None:
    module, law, reference, search = _paths_module(tmp_path, monkeypatch)
    (tmp_path / "# law 캐시_저장내역").mkdir()
    (tmp_path / "# law 캐시_저장내역" / "law_1.json").write_text("본문", encoding="utf-8")
    (tmp_path / "# law 캐시_조문").mkdir()
    (tmp_path / "# law 캐시_조문" / "ref_1.json").write_text("조문", encoding="utf-8")
    (tmp_path / "# law 캐시_검색목록").mkdir()
    (tmp_path / "# law 캐시_검색목록" / "q_1.json").write_text("목록", encoding="utf-8")

    module.migrate_legacy_cache_dirs()

    assert (law / "law_1.json").read_text(encoding="utf-8") == "본문"
    assert (reference / "ref_1.json").read_text(encoding="utf-8") == "조문"
    assert (search / "q_1.json").read_text(encoding="utf-8") == "목록"
    # 비워진 옛 폴더는 남기지 않는다.
    assert not (tmp_path / "# law 캐시_저장내역").exists()


def test_moves_oldest_generation_dirs(tmp_path, monkeypatch) -> None:
    module, law, _, _ = _paths_module(tmp_path, monkeypatch)
    (tmp_path / "저장된_법령").mkdir()
    (tmp_path / "저장된_법령" / "law_9.json").write_text("옛본문", encoding="utf-8")

    module.migrate_legacy_cache_dirs()

    assert (law / "law_9.json").read_text(encoding="utf-8") == "옛본문"


def test_existing_new_file_wins(tmp_path, monkeypatch) -> None:
    # 새 자리에 같은 이름이 있으면 그쪽이 최신이므로 덮어쓰지 않는다.
    module, law, _, _ = _paths_module(tmp_path, monkeypatch)
    law.mkdir(parents=True)
    (law / "law_1.json").write_text("최신", encoding="utf-8")
    (tmp_path / "# law 캐시_저장내역").mkdir()
    (tmp_path / "# law 캐시_저장내역" / "law_1.json").write_text("옛것", encoding="utf-8")

    module.migrate_legacy_cache_dirs()

    assert (law / "law_1.json").read_text(encoding="utf-8") == "최신"


def test_runs_without_legacy_dirs(tmp_path, monkeypatch) -> None:
    # 새로 설치한 사용자는 옮길 것이 없다. 오류 없이 지나가야 한다.
    module, law, _, _ = _paths_module(tmp_path, monkeypatch)
    module.migrate_legacy_cache_dirs()
    assert not law.exists()


@pytest.fixture(autouse=True)
def _restore_paths_module():
    yield
    # 다른 테스트가 실제 경로를 쓰도록 모듈을 원래대로 되돌린다.
    sys.modules.pop("storage.paths", None)
    importlib.import_module("storage.paths")
