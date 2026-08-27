"""리팩터링 회귀 테스트 - 순수 함수의 입출력 고정.

파일을 패키지로 나누는 동안 동작이 바뀌지 않았는지 확인한다.
처음 실행하면 현재 결과를 골든 파일로 저장하고, 이후 실행에서는
저장된 값과 비교한다. 값이 달라지면 그 자리에서 실패한다.

    python tests/test_regression_pure.py            # 비교
    python tests/test_regression_pure.py --update   # 골든 갱신(의도한 변경일 때만)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

GOLDEN_PATH = Path(__file__).with_name("golden_pure.json")


def digest(value: object) -> str:
    """긴 결과는 해시로 비교해 골든 파일이 커지지 않게 한다."""
    text = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_module():
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])
    import molit_cgm_expc_qt as module

    return module


# --- 시험 입력 ---------------------------------------------------------

CITATION_CASES = [
    ("법 제57조제1항의 규정에 의한 위해방지", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("영 제55조제3항제5호가목에서 정하는 경우", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("「건설산업기본법 시행령」 제8조제1항의 규정", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("「주차장법」 제19조에 따른 부설주차장은 같은 법 제19조의4에 따라", "건축법 시행령", "001"),
    ('제2조(공공시설) 「국토의 계획 및 이용에 관한 법률 시행령」(이하 "영"이라 한다) 제4조제2호에서 정한다.',
     "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ('이 지침은 「국토의 계획 및 이용에 관한 법률」(이하 "법"이라 한다) 제25조부터 '
     "제28조까지, 제30조 및 제48조의2에 따라 정한다.", "", ""),
    ("법 제56조제4항 및 제5항, 제57조에 따라", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("제11조(준공검사) 공작물의 설치(「건축법」 제83조에 따라 설치되는 것은 제외한다)",
     "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("영 제70조의3제1항에 따른 통지", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
    ("별지 제6호서식의 개발행위준공검사신청서", "국토의 계획 및 이용에 관한 법률 시행규칙", "009469"),
]

ADMIN_BREAK_CASES = [
    "2-2-4. 1-2-1. 각 호에서 정하고 있는 계획의 일부",
    "④ 개발제한구역 해제 당시 300호 미만으로 ②항 또는 ③항의 집단취락과 결합하여",
    "(2) (1)에도 불구하고 수도권외의 지역에서",
    "4-2-2. ⑤ 각 호에 해당하는 경우 등 필요하다고 인정한 경우",
    "① 항만시설의 설치에 관한 사항",
    "⑩ ①ㆍ②ㆍ⑤ㆍ⑥ㆍ⑧ 및 ⑨의 규정에 의한 도시ㆍ군계획시설결정",
]

SHORT_NAME_CASES = [
    ("국토의 계획 및 이용에 관한 법률", "국토계획법"),
    ("국토의 계획 및 이용에 관한 법률 시행규칙", "국토계획법 시행규칙"),
    ("국토의 계획 및 이용에 관한 법률 시행령", "국토계획법"),
    ("건축법", ""),
    ("산업입지 및 개발에 관한 법률", "산업입지법"),
    ("", ""),
]

SIBLING_CASES = [
    ("건축법 시행규칙", "법"),
    ("건축법", "영"),
    ("도로교통법 시행령", "규칙"),
    ("", "법"),
]


def collect(module) -> dict[str, object]:
    result: dict[str, object] = {}

    result["citations"] = {
        f"{index}": digest(
            module.law_reference_html_text(
                text,
                (),
                current_law_name=law_name,
                current_law_id=law_id,
                use_api_links=True,
            )
        )
        for index, (text, law_name, law_id) in enumerate(CITATION_CASES)
    }
    result["citation_links"] = {
        f"{index}": module.law_reference_html_text(
            text, (), current_law_name=law_name, current_law_id=law_id,
            use_api_links=True,
        ).count("lawref://")
        for index, (text, law_name, law_id) in enumerate(CITATION_CASES)
    }
    result["admin_breaks"] = {
        f"{index}": module.insert_admin_clause_breaks(text).replace("\n", " ⏎ ")
        for index, text in enumerate(ADMIN_BREAK_CASES)
    }
    result["short_names"] = {
        f"{index}": module.law_short_name(name, official)
        for index, (name, official) in enumerate(SHORT_NAME_CASES)
    }
    result["sibling_names"] = {
        f"{index}": module.sibling_law_name(anchor, unit)
        for index, (anchor, unit) in enumerate(SIBLING_CASES)
    }
    result["law_base_names"] = {
        name: module.law_base_name(name) for name, _ in SHORT_NAME_CASES
    }
    result["aliases"] = module.collect_law_aliases(
        '「국토의 계획 및 이용에 관한 법률」(이하 "법"이라 한다) 제25조와 '
        '「같은 법 시행령」(이하 "영"이라 한다) 제4조'
    )

    # 실제 지침 원문이 있으면 통째로 돌려 결과를 고정한다.
    sample = PROJECT_DIR / "perf_sample_guideline.txt"
    if sample.is_file():
        body = module.json_text(sample.read_text(encoding="utf-8"))
        broken = module.insert_admin_clause_breaks(body)
        result["guideline"] = {
            "lines": broken.count("\n") + 1,
            "digest": digest(broken),
            "html_digest": digest(
                module.body_to_html(
                    broken, (), use_api_links=True, administrative_rule=True
                )
            ),
        }

    # 저장된 법령 본문 파싱 결과도 고정한다.
    # 여기서 읽는 것은 저장소에 둔 개발용 표본이다. 프로그램이 실행 중에
    # 쓰는 자리(storage.paths.LAW_CACHE_DIR)는 사용자 폴더라 기계마다
    # 내용이 달라 골든값이 흔들리므로 그쪽을 보지 않는다.
    saved = sorted(
        (PROJECT_DIR / "# law 캐시" / "저장내역").glob("law_*.json")
    )
    if saved:
        record = json.loads(saved[0].read_text(encoding="utf-8"))
        result["saved_law"] = {
            "file": saved[0].name,
            "plain_digest": digest(str(record.get("rendered_plain_text") or "")),
        }
    return result


def main() -> int:
    update = "--update" in sys.argv
    module = load_module()
    current = collect(module)

    if update or not GOLDEN_PATH.is_file():
        GOLDEN_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"골든 저장: {GOLDEN_PATH.name} ({len(current)}개 그룹)")
        return 0

    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []
    for group, expected in golden.items():
        actual = current.get(group)
        if actual != expected:
            if isinstance(expected, dict) and isinstance(actual, dict):
                for key, value in expected.items():
                    if actual.get(key) != value:
                        failures.append(
                            f"{group}[{key}]\n    기대: {value!r}\n    실제: {actual.get(key)!r}"
                        )
            else:
                failures.append(f"{group}\n    기대: {expected!r}\n    실제: {actual!r}")

    for group in current:
        if group not in golden:
            print(f"  (새 그룹 {group} - --update 로 반영하세요)")

    if failures:
        print(f"실패 {len(failures)}건")
        for line in failures:
            print(" -", line)
        return 1
    print(f"통과: {len(golden)}개 그룹, 동작 변화 없음")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
